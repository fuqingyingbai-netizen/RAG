"""Use the packaged DOCX renderer with an isolated Windows console launcher."""
import argparse,hashlib,importlib.util,json,os,sys,tempfile,uuid
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[2];RUN=ROOT/'work/company-phase1-20261028'
parser=argparse.ArgumentParser();parser.add_argument('input',type=Path);parser.add_argument('output',type=Path)
parser.add_argument('--dpi',type=int,default=144);args=parser.parse_args()
assert sys.platform=='win32'
source=args.input.resolve();output=args.output.resolve()
assert source.is_relative_to(ROOT) and output.is_relative_to(ROOT) and source.is_file()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
before=sha(source)
runtime=RUN/'render-runtime';program=runtime/'libreoffice/program';console=program/'soffice.com'
portable=json.loads((runtime/'proof.json').read_text(encoding='utf-8'))
assert sha(program/'soffice.exe')==portable['isolated_executable_sha256'] and console.is_file()
renderer=Path('C:/Users/wangli/.codex/plugins/cache/openai-primary-runtime/documents/26.1029.11837/skills/documents/render_docx.py')
assert renderer.is_file()
# Keep extension-registry paths below Windows path-length limits. This is a
# newly created workspace directory, never a user's desktop Office profile.
scratch=ROOT/'work'/('loqa_'+uuid.uuid4().hex[:8]);scratch.mkdir(exist_ok=False)
assert scratch.resolve().is_relative_to((ROOT/'work').resolve())
tempfile.tempdir=str(scratch);os.environ['TMP']=os.environ['TEMP']=str(scratch)
poppler=runtime/'poppler/poppler-26.09.0/Library/bin'
os.environ['PATH']=str(program)+os.pathsep+str(poppler)+os.pathsep+os.environ.get('PATH','')
spec=importlib.util.spec_from_file_location('company_primary_renderer',renderer)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
# LibreOffice's documented Windows console entry point; the packaged renderer
# performs all OOXML preparation, conversion, pagination and PNG production.
module._resolve_soffice=lambda:str(console.resolve())
output.mkdir(parents=True,exist_ok=True)
sys.argv=[str(renderer),str(source),'--output_dir',str(output),'--dpi',str(args.dpi),'--emit_pdf','--verbose']
module.main()
images=sorted(output.glob('page-*.png'));assert images and sha(source)==before
proof={'at':datetime.now(timezone.utc).isoformat(),'scope':'packaged renderer on isolated Windows portable runtime',
    'input_sha256':before,'input_unchanged':True,'packaged_renderer':str(renderer),'packaged_renderer_sha256':sha(renderer),
    'adapter_sha256':sha(Path(__file__)),'windows_console':str(console),'console_sha256':sha(console),
    'portable_exe_sha256':sha(program/'soffice.exe'),'portable_origin':portable['source_runtime'],
    'not_a_loader_bundled_libreoffice':True,'personal_desktop_installation_used':False,
    'official_console_reference':'https://help.libreoffice.org/latest/en-GB/text/shared/guide/start_parameters.html?DbPAR=WRITER&System=WIN',
    'task_scratch':str(scratch),'dpi':args.dpi,'pages':[{'name':p.name,'sha256':sha(p)} for p in images],
    'visual_review':'pending','shipping_report_acceptance':False}
(output/'renderer-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'pages':len(images),'input_unchanged':True,'visual_review':'pending','shipping_report_acceptance':False}))
