# fix_bom.py
# fix_bom.py
import codecs

file_path = r"D:\uv\RAG(1)\RAG\backend\research_workflow.py"

# 读取文件（包含 BOM）
with open(file_path, 'rb') as f:
    content = f.read()

# 检查并移除 BOM
if content.startswith(codecs.BOM_UTF8):
    content = content[len(codecs.BOM_UTF8):]

# 写回文件
with open(file_path, 'wb') as f:
    f.write(content)

print("✅ BOM 字符已移除")