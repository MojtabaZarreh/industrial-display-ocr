import ast
import json
from pathlib import Path


def test_training_notebook_contains_clean_executable_source():
    path = Path(__file__).resolve().parents[2] / 'notebooks/PP_OCRv6_medium_3datasets.ipynb'
    notebook = json.loads(path.read_text(encoding='utf-8'))
    assert len(notebook['cells']) == 45
    for index, cell in enumerate(notebook['cells']):
        if cell['cell_type'] == 'code':
            assert cell['execution_count'] is None
            assert cell['outputs'] == []
            ast.parse(''.join(cell['source']), filename=f'cell-{index}')
    assert 'mixed_config["Global"]["save_model_dir"]' in ''.join(notebook['cells'][29]['source'])
