const {readFileSync, existsSync} = require('node:fs');
const {resolve, dirname} = require('node:path');
const {Module} = require('node:module');
const ts = require('typescript');

module.exports = function loader(mocks = {}) {
  const cache = new Map();
  function load(file) {
    const filename = resolve(__dirname, '..', file);
    if (cache.has(filename)) return cache.get(filename).exports;
    const mod = new Module(filename);
    cache.set(filename, mod);
    mod.filename = filename;
    mod.paths = Module._nodeModulePaths(dirname(filename));
    const original = mod.require.bind(mod);
    mod.require = id => {
      if (id in mocks) return mocks[id];
      if (id.startsWith('@/') || id.startsWith('.')) {
        const base = id.startsWith('@/') ? resolve(__dirname, '..', id.slice(2)) : resolve(dirname(filename), id);
        const target = [base, base + '.ts', base + '.tsx'].find(existsSync);
        if (target && /\.tsx?$/.test(target)) return load(target);
      }
      return original(id);
    };
    mod._compile(ts.transpileModule(readFileSync(filename, 'utf8'), {
      compilerOptions: {target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, esModuleInterop: true},
    }).outputText, filename);
    return mod.exports;
  }
  return load;
};
