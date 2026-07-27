/**
 * Vercel Serverless Function — 每天定时触发 GitHub Actions pipeline
 *
 * 由 Vercel Cron Jobs 每天 6:00 AM CST 自动调用此接口，
 * 本接口再 POST 到 GitHub Actions dispatch API 触发数据管道运行。
 */

const GITHUB_TOKEN = process.env.GITHUB_TOKEN || '';
const REPO_OWNER = 'ruiqiliang464-creator';
const REPO_NAME = 'stock-agent';
const WORKFLOW_ID = 'daily-pipeline.yml';

export default async function handler(req, res) {
  // 安全验证：只接受 GET（Vercel Cron 调用）和 POST（手动测试）
  if (req.method !== 'GET' && req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  if (!GITHUB_TOKEN) {
    console.error('[Trigger] GITHUB_TOKEN 未配置');
    return res.status(500).json({ error: 'GITHUB_TOKEN not configured' });
  }

  const url = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${WORKFLOW_ID}/dispatches`;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `token ${GITHUB_TOKEN}`,
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'User-Agent': 'StockAgent-VercelCron'
      },
      body: JSON.stringify({ ref: 'main' })
    });

    if (response.status === 204) {
      console.log('[Trigger] ✅ GitHub Actions pipeline 触发成功');
      return res.status(200).json({
        success: true,
        message: 'Pipeline triggered successfully',
        timestamp: new Date().toISOString()
      });
    } else {
      const text = await response.text();
      console.error(`[Trigger] ❌ GitHub API 返回 ${response.status}: ${text}`);
      return res.status(response.status).json({
        success: false,
        error: `GitHub API returned ${response.status}`,
        details: text
      });
    }
  } catch (err) {
    console.error(`[Trigger] ❌ 请求失败: ${err.message}`);
    return res.status(500).json({
      success: false,
      error: err.message
    });
  }
}
