// these should match the ones in the modal container

const process = require('process');
const colors = require('colors');
const prompt = require('prompt-sync')({sigint: true});
const axios = require('axios')

const admin = require('firebase-admin');
try {
	admin.initializeApp({
	  credential: admin.credential.cert(require(`../firestoreServiceAccount.json`)),
	});
} catch (e) {
  true;
}
const firestore = admin.firestore();

let MODAL_APP_URL
let sessionUser
let sessionId


async function main(){
	
	MODAL_APP_URL = process.argv[2]
	sessionUser = process.argv[3]
	sessionId = process.argv[4]
	
	if (!MODAL_APP_URL || !sessionUser || !sessionId) {
		console.log('error : provide sessionUser and sessionId\nexample : node chat https://modaluserexample-clone-interpreter-session-new-session.modal.run/ admin_user demo_session'.brightRed)
		process.exit()
	}	
	console.dir({MODAL_APP_URL,sessionUser,sessionId})
	
	// start modal container app
	axios.post(
		MODAL_APP_URL,
		JSON.stringify({
			sessionUser,
			sessionId,
		}), {
			headers: { "Content-Type": "application/json" },
	})
	
	while (true) {
		const q = prompt('> '.green)
		console.log(`> user : ${q}`.green)
		const timestamp = Date.now()
		await firestore.doc(`userdata/${sessionUser}/session/${sessionId}/messages/${timestamp}`).set({
			timestampCreated: timestamp,
			query: q,
		})
		if (q.trim() === '/done') process.exit(0)
	}
	
	
	
	
}
main()