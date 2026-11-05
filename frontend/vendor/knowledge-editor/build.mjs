import {build} from 'esbuild';
import {createHash} from 'node:crypto';
import {readFile,writeFile,mkdir,readdir} from 'node:fs/promises';
const result=await build({entryPoints:['editor-entry.js'],bundle:true,minify:true,format:'iife',globalName:'KnowledgeNoteEngine',target:['es2020'],write:false,legalComments:'eof'});
const data=result.outputFiles[0].contents,hash=createHash('sha256').update(data).digest('hex').slice(0,12);
const file=`knowledge-note-engine.${hash}.js`;
await writeFile(`../../${file}`,data);
await writeFile('engine.json',JSON.stringify({file,sha256:createHash('sha256').update(data).digest('hex')},null,2)+'\n');
await mkdir('licenses',{recursive:true});
const lock=JSON.parse(await readFile('package-lock.json','utf8'));
const notices=['# Editor third-party notices','','Tiptap and ProseMirror are bundled locally. No editor cloud service is used.',''];
for(const [path,meta] of Object.entries(lock.packages)) {
  if(!path||meta.dev||meta.optional)continue;
  const pkg=JSON.parse(await readFile(`${path}/package.json`,'utf8'));
  const files=(await readdir(path)).filter(name=>/^(license|copying)(\.|$)/i.test(name));
  if(!files.length)throw Error(`Missing license: ${pkg.name}`);
  for(const source of files){const target=pkg.name.replaceAll('/','__')+'-'+source;await writeFile(`licenses/${target}`,await readFile(`${path}/${source}`));notices.push(`- ${pkg.name} ${pkg.version}: [${pkg.license}](licenses/${target})`);}
}
await writeFile('THIRD_PARTY_NOTICES.md',notices.join('\n')+'\n');
console.log(file);
