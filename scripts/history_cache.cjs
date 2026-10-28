const fs = require('node:fs');
const path = require('node:path');
const pause = () => new Promise(resolve => setTimeout(resolve, 1200));
const planFile = '.cache/history-cache-plan.json';

module.exports = async function ({github, core, cache}, mode) {
  if (mode === 'save') {
    for (const {file, key, hit} of JSON.parse(fs.readFileSync(planFile, 'utf8'))) {
      if (!hit && fs.existsSync(file)) {
        await cache.saveCache([file], key);
        core.info(`Saved ${path.basename(file)} as ${key}`);
        await pause();
      }
    }
    return;
  }

  const user = process.env.CONTRIBUTION_USER;
  const source = process.env.CONTRIBUTION_SOURCE || 'auto';
  if (!/^[A-Za-z0-9][A-Za-z0-9-]{0,38}$/.test(user || '') || !['auto', 'graphql', 'public'].includes(source)) {
    throw new Error('Invalid contribution user or source');
  }
  const year = Number(new Intl.DateTimeFormat('en', {year: 'numeric', timeZone: 'Asia/Tokyo'}).format(new Date()));
  let first = Number(process.env.START_YEAR);
  if (!process.env.START_YEAR) {
    const {data} = await github.rest.users.getByUsername({username: user});
    first = Number(data.created_at.slice(0, 4));
    await pause();
  }
  if (!Number.isInteger(first) || first < 1 || first > year) throw new Error('Invalid start year');
  const kind = source === 'public' ? 'public-calendar-api' : 'github-graphql';
  const plan = [];
  for (let historicalYear = first; historicalYear <= year - 2; historicalYear++) {
    const file = path.join('.cache/contributions', kind, user.toLowerCase(), `${historicalYear}.json`);
    const key = `contribution-year-v1-${kind}-${user.toLowerCase()}-${historicalYear}`;
    const matched = await cache.restoreCache([file], key);
    plan.push({file, key, hit: matched === key});
    core.info(`${historicalYear}.json: ${matched === key ? 'cache hit' : 'cache miss'}`);
    await pause();
  }
  fs.mkdirSync('.cache', {recursive: true});
  fs.writeFileSync(planFile, JSON.stringify(plan), 'utf8');
};
