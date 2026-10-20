"""Remove a UTF-8 BOM from an explicitly selected file."""
import argparse
import codecs
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    content = args.path.read_bytes()
    if content.startswith(codecs.BOM_UTF8):
        args.path.write_bytes(content[len(codecs.BOM_UTF8):])
        print('UTF-8 BOM 已移除')
    else:
        print('文件没有 UTF-8 BOM，无需修改')


if __name__ == '__main__':
    main()
