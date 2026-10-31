// Build the Django application and validate its Neon service declaration.
import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
const python = process.env.HROS_PYTHON || (existsSync('.venv/bin/python') ? '.venv/bin/python' : 'python');
const env = {...process.env, DJANGO_LOAD_DOTENV:'False', DJANGO_SETTINGS_MODULE:'payroll_project.settings.test'};
for (const args of [
  ['manage.py', 'check'],
  ['manage.py', 'makemigrations', '--check', '--dry-run'],
  ['manage.py', 'collectstatic', '--noinput'],
]) {
  const result = spawnSync(python, args, {env, stdio:'inherit'});
  if (result.error) { console.error(result.error.message); process.exit(1); }
  if (result.status !== 0) process.exit(result.status || 1);
}
const types = spawnSync(process.execPath, ['node_modules/typescript/bin/tsc', '--noEmit', '--skipLibCheck', '--target', 'ES2022', '--module', 'NodeNext', '--moduleResolution', 'NodeNext', 'neon.ts'], {stdio:'inherit'});
if (types.error || types.status !== 0) process.exit(types.status || 1);
console.log('Build passed: Django checks, migration drift, static assets, and neon.ts types.');
