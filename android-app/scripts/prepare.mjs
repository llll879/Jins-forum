// Кладёт клиент форума внутрь приложения: ../forum.html -> www/index.html,
// подставляя адрес сервера вместо __BASE__ (на сайте это делает forum.py при выдаче страницы).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = path.join(here, '..', '..', 'forum.html');
const out = path.join(here, '..', 'www');
const url = (process.env.SERVER_URL || '').trim().replace(/\/+$/, '');

if (!/^https:\/\/[^\s/]+/.test(url)) {
  console.error('Нужен адрес сервера форума с https://, например SERVER_URL=https://forum.example.com (получено: "' + url + '")');
  process.exit(1);
}
if (!fs.existsSync(src)) {
  console.error('Нет forum.html — сначала выполните: python tools/build_forum.py');
  process.exit(1);
}
const html = fs.readFileSync(src, 'utf8');
if (!html.includes('"__BASE__"')) console.warn('Внимание: в forum.html не нашёл "__BASE__" — адрес сервера не подставлен');
fs.mkdirSync(out, { recursive: true });
fs.writeFileSync(path.join(out, 'index.html'), html.replace(/__BASE__/g, url));
console.log('OK: www/index.html, сервер ' + url);
