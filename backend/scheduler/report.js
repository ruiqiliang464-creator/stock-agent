const mailer = require('../mailer/sender');

async function run() {
  return await mailer.run();
}

module.exports = { run };
