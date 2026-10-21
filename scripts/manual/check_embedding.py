"""Explicit, manual dense-model check. Importing this tool never loads a model."""
import argparse
import os
from pathlib import Path


def main():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / '.env')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=os.getenv('EMBEDDING_MODEL', 'BAAI/bge-m3'))
    parser.add_argument('--device', default=os.getenv('EMBEDDING_DEVICE', 'cpu'))
    parser.add_argument('--text', default='测试医疗RAG')
    args = parser.parse_args()
    from langchain_huggingface import HuggingFaceEmbeddings
    model = HuggingFaceEmbeddings(model_name=args.model, model_kwargs={'device': args.device})
    print('向量维度:', len(model.embed_query(args.text)))


if __name__ == '__main__':
    main()
