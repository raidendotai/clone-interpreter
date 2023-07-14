// these should match the ones in the modal container
const BUCKET_NAME = 'your_cloud_storage_bucket_name'


const process = require('process');
const colors = require('colors');
const admin = require("firebase-admin");
const sanitize = require('sanitize-filename');
const { Storage } = require('@google-cloud/storage');
const serviceAccountCloudStorage = require(`../cloudStorageServiceAccount.json`);
const storage = new Storage({
  credentials: serviceAccountCloudStorage,
});
const bucket = storage.bucket(BUCKET_NAME);
const fs = require("fs");

try {
	admin.initializeApp({
	  credential: admin.credential.cert(require(`../firestoreServiceAccount.json`)),
	});
} catch (e) {
  true;
}
const firestore = admin.firestore();


let sessionUser 
let sessionId

async function storage_download(storage_file) {
	try {fs.mkdirSync(`../session-file-sync/${sessionId}`)}catch(e){false}
  try {
    const filename = sanitize(storage_file);
    const response = await bucket.file(`${sessionUser}/${sessionId}/${storage_file}`).download({
      destination: `../session-file-sync/${sessionId}/${storage_file}`,
    });
    console.log(`> local file sync : ../session-file-sync/${sessionId}/${storage_file}`.green)
  } catch (e) {
    console.log(`${e}`.red);
  }
}


let stack_ids = []
let sync_files = []
async function main(){

	sessionUser = process.argv[2]
	sessionId = process.argv[3]
	
	if (!sessionUser || !sessionId) {
		console.log('error : provide sessionUser and sessionId\nexample : node watch admin_user demo_session'.brightRed)
		process.exit()
	}
	
	console.dir({sessionUser,sessionId})
	
	firestore.collection(`userdata/${sessionUser}/session/${sessionId}/stack`).orderBy('timestamp','desc').limit(15).onSnapshot( (col) => {
		col.docs.map( (doc)=>{
			if (!stack_ids.includes(doc.id)) {
				stack_ids.push(doc.id)
				const stack_entry = doc.data()
				console.log(`> stack entry : ${stack_entry.type}`.yellow)
				console.log(`${stack_entry.data}`.cyan)
				
				if (stack_entry.type === `files_state`) {
					const file_list = JSON.parse(stack_entry.data)
					file_list.map( (f) => {
						
						if ( !sync_files.includes(f.md5) ) {
							sync_files.push(f.md5)
							storage_download(f.path)
						}
					})
				}
			}
		})
	});
	
	
	
}
main()