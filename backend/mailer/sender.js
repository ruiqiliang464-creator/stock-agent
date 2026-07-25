const nodemailer = require('nodemailer');
const { prepare, saveDb } = require('../db');
const { generateReport, generateSummary } = require('../formatter/report');

// QQ邮箱SMTP配置
const SMTP_CONFIG = {
  host: process.env.SMTP_HOST || 'smtp.qq.com',
  port: parseInt(process.env.SMTP_PORT) || 465,
  secure: process.env.SMTP_SECURE === 'true' || true,
  auth: {
    user: process.env.SMTP_USER || '',
    pass: process.env.SMTP_PASS || ''
  }
};

function createTransporter() {
  return nodemailer.createTransport(SMTP_CONFIG);
}

async function sendReportEmail(toEmail, htmlContent, date) {
  if (!SMTP_CONFIG.auth.user || !SMTP_CONFIG.auth.pass) {
    console.error('[Mailer] SMTP账号密码未配置，无法发送邮件');
    console.error('[Mailer] 请在 config/default.env 中设置 SMTP_USER 和 SMTP_PASS');
    return false;
  }

  const transporter = createTransporter();

  const mailOptions = {
    from: `"Stock Agent 每日情报" <${SMTP_CONFIG.auth.user}>`,
    to: toEmail,
    subject: `每日市场情报 ${date}`,
    html: htmlContent,
    // 纯文本备选
    text: `每日市场情报 ${date} - 请查看HTML版本获取完整内容`
  };

  try {
    const info = await transporter.sendMail(mailOptions);
    console.log(`[Mailer] 邮件发送成功: ${toEmail}, MessageId: ${info.messageId}`);
    return true;
  } catch (e) {
    console.error(`[Mailer] 邮件发送失败: ${toEmail}`, e.message);

    // 重试1次
    try {
      const info2 = await transporter.sendMail(mailOptions);
      console.log(`[Mailer] 重试成功: ${toEmail}`);
      return true;
    } catch (e2) {
      console.error(`[Mailer] 重试也失败: ${toEmail}`, e2.message);
      return false;
    }
  }
}

async function run() {
  console.log('[Report Scheduler] 开始邮件推送...');

  const fs = require('fs');
  const path = require('path');
  const today = new Date().toISOString().split('T')[0];
  const analysisPath = path.join(__dirname, '..', '..', 'data', `analysis_${today}.json`);

  if (!fs.existsSync(analysisPath)) {
    console.log('[Report Scheduler] 无分析数据，跳过推送');
    return;
  }

  const analysis = JSON.parse(fs.readFileSync(analysisPath, 'utf-8'));

  // 生成HTML报告
  const htmlContent = generateReport(analysis);
  const summary = generateSummary(analysis);

  // 保存报告到数据库
  try {
    prepare(`
      INSERT OR REPLACE INTO reports (date, html_content, summary) VALUES (?, ?, ?)
    `).run(today, htmlContent, summary);
    saveDb();
  } catch (e) {
    console.error('[Report Scheduler] 报告入库失败:', e.message);
  }

  // 获取所有开启推送的用户邮箱
  const users = prepare(`
    SELECT u.email, u.push_email, us.push_enabled
    FROM users u JOIN user_settings us ON u.id = us.user_id
    WHERE us.push_enabled = 1
  `).all();

  if (users.length === 0) {
    console.log('[Report Scheduler] 无用户开启推送，跳过');
    return;
  }

  // 逐个推送
  const results = [];
  for (const user of users) {
    const targetEmail = user.push_email || user.email;
    const success = await sendReportEmail(targetEmail, htmlContent, today);
    results.push({ email: targetEmail, success });
  }

  console.log(`[Report Scheduler] 推送完成: ${results.filter(r => r.success).length}/${results.length} 成功`);
  return results;
}

module.exports = { run, sendReportEmail };
