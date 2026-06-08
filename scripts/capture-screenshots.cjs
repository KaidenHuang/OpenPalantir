const { chromium } = require('playwright');
const { join } = require('path');
const { mkdirSync } = require('fs');

const docsDir = join(__dirname, '..', 'docs');
const baseUrl = 'http://127.0.0.1:5175';

mkdirSync(docsDir, { recursive: true });

async function screenshot(page, name, action) {
  console.log(`截取: ${name}`);
  await action(page);
  await page.waitForTimeout(1500);
  await page.screenshot({ path: join(docsDir, `${name}.png`), fullPage: false });
  console.log(`  完成: ${name}.png`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();

  try {
    await page.goto(baseUrl, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(2000);

    // 1. 文档管理
    await screenshot(page, '文档管理页面', async (p) => {
      await p.click('button:has-text("文档管理")');
      await p.waitForTimeout(2000);
    });

    // 2. 数据库管理
    await screenshot(page, '数据库管理页面', async (p) => {
      await p.click('button:has-text("数据库管理")');
      await p.waitForTimeout(2000);
    });

    // 3. 实体管理
    await screenshot(page, '实体管理页面', async (p) => {
      await p.click('button:has-text("实体管理")');
      await p.waitForTimeout(2000);
    });

    // 4. 图谱可视化
    await screenshot(page, '图谱可视化页面', async (p) => {
      await p.click('button:has-text("图谱可视化")');
      await p.waitForTimeout(3000);
    });

    // 5. 任务管理
    await screenshot(page, '任务管理页面', async (p) => {
      await p.click('button:has-text("任务管理")');
      await p.waitForTimeout(2000);
    });

    // 6. 模型管理
    await screenshot(page, '模型管理页面', async (p) => {
      await p.click('button:has-text("模型管理")');
      await p.waitForTimeout(2000);
    });

    // 7. 分析报告 - 路径分析
    await screenshot(page, '路径分析页面', async (p) => {
      await p.click('button:has-text("分析报告")');
      await p.waitForTimeout(1000);
      await p.click('button:has-text("路径分析")');
      await p.waitForTimeout(1000);
    });

    // 8. 分析报告 - 社区分析
    await screenshot(page, '社区分析页面', async (p) => {
      await p.click('button:has-text("社区分析")');
      await p.waitForTimeout(1000);
    });

    // 9. 分析报告 - 中心性分析
    await screenshot(page, '中心性分析页面', async (p) => {
      await p.click('button:has-text("中心性分析")');
      await p.waitForTimeout(1000);
    });

    // 10. 分析报告 - 趋势分析
    await screenshot(page, '趋势分析页面', async (p) => {
      await p.click('button:has-text("趋势分析")');
      await p.waitForTimeout(1000);
    });

    // 11. 智能决策
    await screenshot(page, '智能决策页面', async (p) => {
      await p.click('button:has-text("智能决策")');
      await p.waitForTimeout(2000);
    });

    console.log('\n所有截图完成！');
  } catch (err) {
    console.error('截图过程出错:', err);
    process.exit(1);
  } finally {
    await browser.close();
  }
})();
