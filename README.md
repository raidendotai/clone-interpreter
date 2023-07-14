# clone-interpreter ✨

a fully replicated OpenAI GPT Code Interpreter sandbox, that is deployable to modal

*public web app coming in the next few days*



updates on twitter [@n_raidenai](https://twitter.com/n_raidenai)

### 

### Features

* Full control over sandbox environment
  
  * internet access
  
  * custom packages installs
  
  * deployable to modal (which has GPU availability)

* Realtime session persistence
  
  * user messages
  
  * generated code / texts
  
  * generated files
  
  * can be wrapped in an API

* Custom commands. Current examples :
  
  * `/run` and `/run_bg` for shell commands
    
    * i.e. `/run ls -la`
  
  * `/upload` for file transfer to sandbox
    
    * i.e. `/upload https://example.com/some.pdf`
  
  * (soon) `/doc` for fast document interaction, to simulate
    
    * i.e. `/doc https://example.com/paper.pdf what are the main conclusions presented in the abstract`
  
  * `/done` to close session

### How To

*note: the web app will be available in a few days, and will abstract away a lot of the configuration steps below*

##### You need :

* a [modal](https://modal.com) account : to deploy the sandbox

* a [firebase](https://firebase.google.com/) project with firestore enabled : for chat message subscriptions and session persistence

* a [cloud storage](https://cloud.google.com/storage) bucket : to store and access files generated in the sandbox

##### Steps :

* installs & service accounts
  
  * clone the repo
  
  * install python packages `pip install -r requirements.txt`
  
  * configure [modal](https://modal.com/docs/guide) if you haven't done so yet
  
  * to install chat cli, which is used to interact with the sandbox *(temporary solution until web app is done)*, you need to have nodeJS installed, run :
    
    * `cd cli && npm i`
  
  * create service accounts credentials and save them in the root folder, for :
    
    * firestore
      
      * save it as `firestoreServiceAccount.json`
      
      * [see how to](https://clemfournier.medium.com/how-to-get-my-firebase-service-account-key-file-f0ec97a21620)
    
    * cloud storage
      
      * save it as `cloudStorageServiceAccount.json`
      
      * [see how to](https://stackoverflow.com/questions/46287267/how-can-i-get-the-file-service-account-json-for-google-translate-api)

* Config & deploy
  
  * open `modal_app.py`, configure the variables at the top of the file as you see fit
  
  * from root folder, run `modal deploy modal_app.py`. *(note: the first build takes a lot of time, i'll push to dockerhub later on to speed this step up. after the first build, it will only take few seconds for each update)* after the build, it should output :
    
    * ```
      ✓ Created objects.
      ├── 🔨 Created new_session => https://{MODAL_USER}--clone-interpreter-session-new-session.modal.run
      ✓ App deployed! 🎉
      ```
  
  * to configure the sandbox url in the chat cli,
    
    * open `cli/new_session.js` and replace the `MODAL_APP_URL` with the URL your received above:
      
      * `const MODAL_APP_URL = 'https://{MODAL_USER}--clone-interpreter-session-new-session.modal.run/'`
    
    * open `cli/watch.js` and replace your cloud storage bucket name, to match the one you specified in the `modal_app.py` config:
      
      * `const BUCKET_NAME = 'your_cloud_storage_bucket_name'`
  
  * that's all

* How to interact
  
  * Chat CLI :
    
    * `cd cli`, then
    
    * `node new_session`, it will output 2 node commands, run each in a different shell from the same `cli` folder:
      
      * `node watch demo_user example01b1ff2670ba9c06ee1b2f90992b88ce`
        
        * observes the session in real time and logs every update
        
        * downloads the files generated in the sandbox, saved under `session-file-sync` folder in root
      
      * `node chat https://{MODAL_USER}--clone-interpreter-session-new-session.modal.run/ demo_user example01b1ff2670ba9c06ee1b2f90992b88ce`
        
        * is used to chat with to the sandbox
        
        * *note: i still haven't added queuing and will probably do alongside the web app, so make sure you only send messages when the observer (the watch shell) is inactive*
  
  * Web app :
    
    * soon

* How to Play
  
  * Custom commands examples:
    
    * `/run ls -la` to run a shell command and wait for output
    
    * `/run_bg some_command some_args` to start a shell command in background
    
    * `/upload https://example.com/dataset.csv` to have the file inside the sandbox
    
    * *(soon)* `/doc https://example.com/paper.pdf list the benefits of swimming` to do operations on documents
  
  * To close a session, send `/done` command in the chat, otherwise the session stays open until timeout and consumes your modal credits uselessly

---

Show what you're building with clone-intepreter, reach out on twitter [@n_raidenai](https://twitter.com/n_raidenai)