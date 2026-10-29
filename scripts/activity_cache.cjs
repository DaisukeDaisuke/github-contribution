// Only Actions cache stores the private generation inputs; never the image branch.
const fs = require('node:fs');
const planFile = '.cache/activity-cache-plan.json';
module.exports = async function ({core, cache}, mode) {
  if (mode === 'save') {
    const {file, key, hit} = JSON.parse(fs.readFileSync(planFile, 'utf8'));
    if (!hit && fs.existsSync(file)) await cache.saveCache([file], key);
    return;
  }
  const user = (process.env.CONTRIBUTION_USER || '').toLowerCase();
  if (!/^[a-z0-9][a-z0-9-]{0,38}$/.test(user)) throw new Error('Invalid activity user');
  const scope = process.env.ACTIVITY_SCOPE === 'accessible' ? 'accessible' : 'public';
  const prefix = `activity-v4-${scope}-${user}-`;
  // ISO week: Thursday determines the week-year, including New Year boundaries.
  const date = new Date();
  date.setUTCHours(0, 0, 0, 0);
  date.setUTCDate(date.getUTCDate() + 4 - (date.getUTCDay() || 7));
  const year = date.getUTCFullYear();
  const week = Math.ceil(((date - new Date(Date.UTC(year, 0, 1))) / 86400000 + 1) / 7);
  const key = prefix + `${year}-W${String(week).padStart(2, '0')}`;
  const file = `.cache/activity/${scope}/${user}/snapshot.json`;
  const matched = await cache.restoreCache([file], key, [prefix]);
  fs.mkdirSync('.cache', {recursive: true});
  fs.writeFileSync(planFile, JSON.stringify({file, key, hit: matched === key}), 'utf8');
  core.info(matched === key ? 'Activity: weekly cache hit' : 'Activity: refresh statistics');
};
