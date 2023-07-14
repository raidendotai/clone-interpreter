const crypto = require('crypto')
const colors = require('colors')

const MODAL_APP_URL = 'https://{MODAL_USER}--clone-interpreter-session-new-session.modal.run/'
const sessionUser = 'demo_user'
const sessionId = crypto.randomBytes(16).toString("hex")

console.log(
	`> run these two commands in separate shells (from this same folder) to interact with the sandbox:\n`.brightRed
)

console.log(
	`node watch ${sessionUser} ${sessionId}\n`.cyan
	+ `node chat ${MODAL_APP_URL} ${sessionUser} ${sessionId}\n`
	.cyan
)