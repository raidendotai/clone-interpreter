###### CONFIG ----------------------------------------------------

### keys
OPENAI_KEY = 'sk-?'
OPENAI_MODEL = 'gpt-?' #'gpt-3.5-turbo-16k-0613'
CLOUDSTORAGE_BUCKET = 'your_cloud_storage_bucket_name'

# pip packages to install before entering main loop (to not rebuild whole docker container, lengthy process)
PRE_INSTALL = ''

### sandbox config
SESSION_TIMEOUT = 5*60 # in seconds
SESSION_CODE_RETRIES = 6 # number of errorfixing attempts for each generated code error
SESSION_COMPLETION_RETRIES = 5 # number of gpt completion attempts (ie. sometimes it may return badly formatted answers)
SESSION_GPT_STACK = 20 # conversation memory stack, how many previous messages to add to completion query

# completion messages stack tokens cutoff
# to allow for GPT to reply, in case stack of previous messages > tokenlimit and needs hard cutoff
SESSION_GPT_REPLY_TOKENS_HARD_CUTOFF = 8000 # ie 10k tokens cutoff always leaves 6k for gpt-3.5-turbo-16k-0613 to reply
SESSION_GPT_SYSTEM_PROMPT = 'you are an expert engineer that writes python code to run in a jupyter cell. include all the necessary imports !'
SESSION_PERSIST_FILE_UPLOADS = True # persist the files you upload via command ie. "/upload https://example.com/file.pdf" to cloud storage




###### IMPORTS ----------------------------------------------------

import sys, datetime, threading, subprocess, os, uuid, shutil, time
import openai, requests, json, hashlib, backoff, tiktoken
import urllib.request
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from google.cloud import storage
from time import sleep
from typing import List, Dict
from pydantic import BaseModel
from urllib.parse import urlparse
import IPython as ipy
from IPython.terminal.interactiveshell import TerminalInteractiveShell
import modal
from modal import web_endpoint
from pathlib import Path
from cryptography.fernet import Fernet

###### INITIALIZE ----------------------------------------------------
# generate dotenv to encrypt and import service accounts into modal container

try:
    key = Fernet.generate_key()
    fernet = Fernet(key)
    FIRESTORE = Path('firestoreServiceAccount.json').read_text()
    CLOUDSTORAGE = Path('cloudStorageServiceAccount.json').read_text()
    FIRESTORE_ENC = fernet.encrypt(FIRESTORE.encode())
    CLOUDSTORAGE_ENC = fernet.encrypt(CLOUDSTORAGE.encode())
    with open('.env', 'w') as outfile:
        outfile.write(f'SERVICES_ENC_KEY = {key.decode()}\nFIRESTORE = {FIRESTORE_ENC.decode()}\nCLOUDSTORAGE = {CLOUDSTORAGE_ENC.decode()}')
except:
    # wont run in deployed sandbox, only during deployment setup
    False

# files to ignore when persisting session files
INIT_FILES = [
    'modal-container.py',
    'firestoreServiceAccount.json',
    'cloudStorageServiceAccount.json',
    '__pycache__/modal-container.cpython-38.pyc',
    '.ipython/profile_default/startup/README',
    '.ipython/profile_default/history.sqlite',
    '.cache/matplotlib/fontlist-v330.json',
    '.wget-hsts',
    '.profile',
    '.bashrc',
]

### init sandbox
shell = TerminalInteractiveShell.instance() #ipy.InteractiveShell.instance()
shell.autoawait = False # prevent plots opening from blocking script execution
shell.automagic = False
# prevent matplotlib plots from opening
shell.run_cell("import matplotlib ; matplotlib.use('agg')")

app = False
db = False
storage_client = False
bucket = False


openai.api_key = OPENAI_KEY

### threading for async
callback_done = threading.Event()
### state variables, set dynamically
sessionId = False
sessionUser = False
sessionStack = [] # equivalent of jupyter notebook, contains every user query, prompt, generated code, execution and files changes as blocks
sessionFiles = [] # current files in session, updated by watch_files()
sessionUploads = []
sessionTime = 0 # elapsed


###### MAIN LOGIC ----------------------------------------------------

### helpers

@backoff.on_exception(backoff.expo, openai.error.RateLimitError)
def gptCompletion(**kwargs):
    # exp backoff retry
    print(f'> gptCompletion()')
    return openai.ChatCompletion.create(**kwargs)

# schema
class GPTCodeResponse(BaseModel):
    full_python_code_to_run_in_jupyter_cell: str
gpt_code_schema = GPTCodeResponse.schema()

# run shell command in background, on different thread
class Command(object):
    def __init__(self, cmd):
        self.cmd = cmd
        self.process = None

    def run(self, timeout=0, **kwargs):
        def target(**kwargs):
            self.process = subprocess.Popen(self.cmd, **kwargs)
            self.process.communicate()

        thread = threading.Thread(target=target, kwargs=kwargs)
        thread.start()
        return True

# file io & cloud storage
def _download(url): return True
def _upload_cloudStorage(): return True
def _download_cloudStorage(): return True

# for loading full sessions states, later
#def _preload_session(): return True


def stack_add(stack_entry):
    # append
    sessionStack.append(stack_entry)
    
    # print stack state
    print('> sessionStack updated, current stack :\n')
    print('-------------------------------------------------------')
    for idx,e in enumerate( sessionStack[-SESSION_GPT_STACK:] ) :
        print(f"{idx} : {e}\n")
    print('-------------------------------------------------------')
    # add to firestore notebook collection (id = timestamp)
    db.collection('userdata').document(sessionUser).collection('session').document(sessionId).collection('stack').document(uuid.uuid1().hex).set({
        "type": stack_entry['type'],
        "data": json.dumps( stack_entry['data'] ),
        "timestamp": time.time()
    })
    
    # update firestore session entry
    False

def watch_uploads():
    False
def watch_files():
    global sessionFiles
    global sessionUploads
    global sessionUser
    global sessionId
    root = '.'
    # watch files (besides files present on init)
    previous_sessionFiles = [*sessionFiles]
    sessionFiles = [ {"path":os.path.normpath( os.path.join(path, name) ), "md5":hashlib.md5(open(os.path.join(path, name), 'rb').read()).hexdigest() } for path, subdirs, files in os.walk(root) for name in files if os.path.normpath( os.path.join(path, name) ) not in INIT_FILES]
    
    previous_sessionFiles_dict = {}
    sessionFiles_dict = {}
    for f in previous_sessionFiles: previous_sessionFiles_dict[f['path']] = f['md5']
    for f in sessionFiles: sessionFiles_dict[f['path']] = f['md5']
    
    print({"previous_sessionFiles_dict":previous_sessionFiles_dict})
    print({"sessionFiles_dict":sessionFiles_dict})
    
    if str(previous_sessionFiles) != str(sessionFiles):

        # temporary : move to file-sync
        # [ shutil.copy(f['path'], '../file-sync') for f in sessionFiles]
        # upload
        for f in sessionFiles:
            if (f not in sessionUploads) or (SESSION_PERSIST_FILE_UPLOADS and f in sessionUploads) :
                if (f['path'] not in previous_sessionFiles_dict) or (sessionFiles_dict[f['path']] != previous_sessionFiles_dict[f['path']]) :
                    filename = f['path']
                    print(f'> uploading {filename}')
                    blob = bucket.blob(f'{sessionUser}/{sessionId}/{filename}')
                    blob.upload_from_filename(f['path'])
        # push files_state to session stack
        stack_add({"type":"files_state","data":sessionFiles})
        # persist files_state to firestore?
        False

tiktoken_encoding = tiktoken.get_encoding("cl100k_base")

def count_tokens(text):
    try:
        return len( tiktoken_encoding.encode(text) )
    except:
        return 0

def _make_gptstack():
    # conversation memory stack
    # returns messages[]
    '''
    all stack entries types :
        role - user
            prompt_text
            prompt_code
            execution_success
            execution_fail
            execution_shell
            files_state
            
        role - assistant
            generated_text
            generated_code
    '''

    # make substack of n=SESSION_GPT_STACK
    _substack = []
    for e in sessionStack[-SESSION_GPT_STACK:]:
        _type = e['type']
        _data = e['data']
        
        if _type in ['prompt_text','prompt_code']:
            _substack.append({"role":"user","content":_data,"tokens":count_tokens(_data)})
        elif _type == 'execution_success':
            m = f'EXECUTION SUCCESS :\n```\n{_data}\n```'
            _substack.append({"role":"user","content":m,"tokens":count_tokens(m)})
        elif _type == 'execution_fail':
            m = f'EXECUTION ERROR :\n```\n{_data}\n```\n\nfix the code!'
            _substack.append({"role":"user","content":m,"tokens":count_tokens(m)})
        elif _type == 'execution_shell':
            shell_cmd_query = e['query']
            m = f'SHELL COMMAND :\n```\n{shell_cmd_query}\n```\n\n'
            m += f'SHELL COMMAND EXECUTION OUTPUT :\n```\n{_data}\n```'
            _substack.append({"role":"user","content":m,"tokens":count_tokens(m)})            
        elif _type == 'files_state':
            files = '\n'.join([f['path'] for f in _data])
            m = f'UPDATED FILES - CURRENT LIST OF FILES :\n```\n{files}\n```'
            _substack.append({"role":"user","content":m,"tokens":count_tokens(m)})   
            
        elif _type in ['generated_text','generated_code']:
            _substack.append({"role":"assistant","content":_data,"tokens":count_tokens(_data)})
            
    # hard cutoff with tiktoken, using n=SESSION_GPT_REPLY_TOKENS_HARD_CUTOFF, to leave tokens for reply
    messages = []
    total_tokens = count_tokens( SESSION_GPT_SYSTEM_PROMPT )
    
    for e in list(reversed(_substack)):
        if total_tokens + e["tokens"] <= SESSION_GPT_REPLY_TOKENS_HARD_CUTOFF:
            total_tokens += e["tokens"]
            messages.append(e)
        else:
            break
            
    messages = [
        {"role":"system","content":SESSION_GPT_SYSTEM_PROMPT},
        *list(reversed(messages))
    ]    
    # filter out tokens data from messages and return
    return [{'role':e['role'] , 'content':e['content'] } for e in messages]


def call_gpt(query_type):
    # query_type : text || code
    
    current_trial = -1
    success = False
    response = False
    
    substack = _make_gptstack()
    # print(f'> call_gpt() substack :\n{substack}')
    
    while (not success) and (current_trial < SESSION_COMPLETION_RETRIES):
        current_trial += 1
        try:
            if query_type == 'text':
                response = gptCompletion(
                    model = OPENAI_MODEL,
                    messages = substack
                )
                print(f'> call_gpt() response:\n{response.choices[0].message}')
                return {"type":"generated_text","data":response.choices[0].message.content}
            else:
                response= gptCompletion(
                    model= OPENAI_MODEL,
                    messages= substack,
                    functions= [
                        {
                          "name": "full_generated_python_code_to_send_to_jupyter_cell_api",
                          "description": "Write the python code to run in a jupyter cell. make sure your response contains all the code needed.",
                          "parameters": gpt_code_schema
                        }
                    ],
                    function_call= {"name": "full_generated_python_code_to_send_to_jupyter_cell_api"}
                )
                print(f'> call_gpt() response:\n{response.choices[0].message}')
                
                return {
                    "type":"generated_code",
                    "data": json.loads(response.choices[0]["message"]["function_call"]["arguments"] , strict=False)['full_python_code_to_run_in_jupyter_cell']
                }
            success = True
        except Exception as e:
            print(f'>call_gpt error\n{e}')
            
    return {'type':'error', 'data':'GPT completion error'}


### custom commands
SESSION_COMMANDS = ['/done' , '/m', '/upload', '/doc', '/run' , '/run_bg' ]
def _handlecommand_m(msg):
    # message without code loop (normal GPT assistant)
    # ie command : '/m do you think i can do X with Y?'
    return {"type":"prompt_text","data":msg}
def _handlecommand_doc(msg):
    # WIP ...
    # ie command : '/doc example.pdf extract the lessons from the abstract'
    # should handle any readable file (doc,codefile,csv,...)
    url_or_file = msg.split(' ')[0].strip()
    query = (' '.join(msg.split(' ')[1:]) ).strip()
    # download/load file
    # add to sessionUploads
    # make prompt
    docprompt = False
    return {"type":"prompt_text","query":msg,"data":docprompt}
def _handlecommand_upload(msg):
    # ie command : '/upload https://whatever.com/example.pdf'
    # or specifcy filename '/upload https://whatever.com/example.pdf yourname.pdf'
    _msg = msg.strip().split(' ')
    url = _msg[0].strip()
    filename = False
    if not len(_msg) > 1: filename = os.path.basename(urlparse(url).path)
    else : filename = (' '.join(_msg[1:]) ).strip()
    # download file
    urllib.request.urlretrieve(url, filename)
    # add to sessionUploads
    sessionUploads.append(filename)
    return {"type":"file_upload","query":msg,"data":filename}    
def _handlecommand_run(msg):
    # run shell command synchronously
    output = subprocess.getoutput(msg)
    return {"type":"execution_shell","query":msg,"data":output}
def _handlecommand_run_bg(msg):
    # run shell command in background
    command = Command(msg)
    command.run(timeout=total_seconds, shell=True)
    return {"type":"execution_shell","query":msg,"data":"background process started"}
def handle_session_command(message):
    global sessionTime
    global SESSION_TIMEOUT
    command = message.split(' ')[0]
    if command == '/done':
        print('> received /done , now exiting by timeout')
        sessionTime = SESSION_TIMEOUT
    data = ' '.join(message.split(' ')[1:])
    if command == '/m': return _handlecommand_m(data)
    try:
        if command == '/upload': return _handlecommand_upload(data)
        elif command == '/doc': return _handlecommand_doc(data)
        elif command == '/run': return _handlecommand_run(data)
        elif command == '/run_bg': return _handlecommand_run_bg(data)
    except Exception as e:
        print('> error :\n{e}\n\n')
        return {"type":"command_error","query":message,"data":f'{e}'}
def handle_session_code_prompt(message):
    return {
        "type":"prompt_code",
        "data": f'USER REQUEST :\n```\n{message}\n```\n\nwrite the python code, make sure all necessary imports are included'
    }










def process_query(firestoreEntry):
    # default behavior uses code handler, see commands for other usage
    
    messageId = firestoreEntry.id ; messageData = firestoreEntry.to_dict()
    message_timestamp = messageData['timestampCreated']
    message = messageData['query']
    print(f'> new user message : id {messageId}\n{message}\n\n')
    
    entry = False
    if message.split(' ')[0] in SESSION_COMMANDS: entry = handle_session_command(message)
    else: entry = handle_session_code_prompt(message)
    
    # push entry to stack
    stack_add(entry)
    
    if entry['type'] == 'prompt_text':
        response = call_gpt('text')
        # push response to stack
        stack_add({ "type":"generated_text", "data":response['data'] })

    elif entry['type'] == 'prompt_code':
        # init conditions
        current_trial = -1
        success = False
        
        while (not success) and (current_trial < SESSION_CODE_RETRIES) :
            current_trial += 1
            response = call_gpt('code')
            generated_code = response['data']
            # push generated_code to stack
            stack_add({ "type":"generated_code", "data":generated_code })

            try:
                execution = shell.run_cell(generated_code)
                execution.raise_error()
                success = True
                print({"> execution success": execution.result})
                stack_add({ "type":"execution_success", "data": execution.result })
            
            except Exception as e:
                print({"> execution error":e})
                stack_add({ "type":"execution_fail", "data": f'{e}' })
            
        watch_files()
    elif entry['type'] == 'file_upload':
        watch_files()
    print('> process_query() done')

# later, load_session
# def load_session(sessionId): return True
# event loop based on firestore message subscription
def on_snapshot(col_snapshot, changes, read_time):
    if (len(col_snapshot)):
        # load message
        firestoreEntry = col_snapshot[0]
        # tag session as busy in firestore
        False
        # process user query
        process_query(firestoreEntry)
        # tag session as not busy in firestore
        False
        callback_done.set()
    
    
###################################

# local test
"""
def new_session():
    # init session in firestore
    print('> firestore subscription')
    firestorePath = f'userdata/{sessionUser}/session/{sessionId}/messages'
    col_query = db.collection(firestorePath).order_by('timestampCreated',direction=firestore.Query.DESCENDING).limit(1)
    query_watch = col_query.on_snapshot(on_snapshot)
    # main loop 
    sessionTime = 0
    print({"sessionUser":sessionUser,"sessionId":sessionId})
    while sessionTime<SESSION_TIMEOUT:
        sleep(1)
        sessionTime+=1
    return 1
    
sessionUser = 'admin'
sessionId = 'demo'
new_session()
"""



stub = modal.Stub("clone-interpreter-session")
clone_interpreter_image = modal.Image.from_dockerfile("Dockerfile")

@stub.function(image=clone_interpreter_image , secret=modal.Secret.from_dotenv())
@web_endpoint(method='POST')
def new_session(req: Dict):
    global sessionUser
    global sessionId
    global sessionTime
    
    global app
    global db
    global storage_client
    global bucket
    
    print('> loading service accounts from env')
    
    enc_key = os.environ['SERVICES_ENC_KEY'].encode()
    enc_firestore = os.environ['FIRESTORE'].encode()
    enc_cloudstorage = os.environ['CLOUDSTORAGE'].encode()
    fernet = Fernet(enc_key)
    
    firestoreServiceAccJsonString = fernet.decrypt(enc_firestore).decode()
    cloudstorageServiceAccJsonString = fernet.decrypt(enc_cloudstorage).decode()
    print({"secret_firestore": firestoreServiceAccJsonString, "secret_cloudstorage" : cloudstorageServiceAccJsonString })
    with open('firestoreServiceAccount.json', 'w') as outfile: outfile.write(firestoreServiceAccJsonString)
    with open('cloudStorageServiceAccount.json', 'w') as outfile: outfile.write(cloudstorageServiceAccJsonString)
    
        
    app = firebase_admin.initialize_app(credentials.Certificate('firestoreServiceAccount.json'))
    db = firestore.client()
    storage_client = storage.Client.from_service_account_json('cloudStorageServiceAccount.json')
    bucket = storage_client.get_bucket(CLOUDSTORAGE_BUCKET)    
    
    sessionUser = req['sessionUser']
    sessionId = req['sessionId']
    sessionTime = 0
    # pre_installs to not rebuild entire docker during tests
    if len(PRE_INSTALL): os.system(f'pip install {PRE_INSTALL}')
    # init session in firestore
    print('> firestore subscription')
    firestorePath = f'userdata/{sessionUser}/session/{sessionId}/messages'
    col_query = db.collection(firestorePath).order_by('timestampCreated',direction=firestore.Query.DESCENDING).limit(1)
    query_watch = col_query.on_snapshot(on_snapshot)
    # main loop
    print({"sessionUser":sessionUser,"sessionId":sessionId,"session_timeout":SESSION_TIMEOUT})
    while sessionTime < SESSION_TIMEOUT:
        sleep(0.5)
        sessionTime += 0.5
    stack_add({'type':'session_closed','data':f'either closed by used /end or timed out after {SESSION_TIMEOUT} seconds'})
    return 1

"""
@stub.local_entrypoint()
def main():
    # on frontend, following should be user provided
    global sessionUser
    global sessionId
    sessionUser = 'admin'
    sessionId = 'demo' # uuid.uuid1().hex
    new_session.call(sessionUser,sessionId)
"""