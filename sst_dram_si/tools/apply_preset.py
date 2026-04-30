#!/usr/bin/env python3
import json, sys, os, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESET_DIR = os.path.join(ROOT, 'configs', 'presets')
TARGET = os.path.join(ROOT, 'local_run_config.json')

def load_json(p):
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(p, obj):
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write('\n')
    shutil.move(tmp, p)

def main():
    if len(sys.argv) < 2:
        print('Usage: apply_preset.py <preset-name|path> [--show-diff]')
        print('Available presets:')
        for fn in sorted(os.listdir(PRESET_DIR)):
            if fn.endswith('.json'):
                print(' -', fn[:-5])
        sys.exit(1)
    preset = sys.argv[1]
    show = '--show-diff' in sys.argv
    # resolve preset path
    if os.path.isfile(preset):
        pp = preset
    else:
        pp = os.path.join(PRESET_DIR, preset if preset.endswith('.json') else preset + '.json')
    if not os.path.isfile(pp):
        print('Preset not found:', pp)
        sys.exit(2)

    base = {}
    if os.path.isfile(TARGET):
        base = load_json(TARGET)
    over = load_json(pp)
    new = dict(base)
    new.update(over)

    if show:
        print('Changes:')
        for k in sorted(set(list(base.keys()) + list(over.keys()))):
            b = base.get(k, '<unset>')
            a = new.get(k, '<unset>')
            if b != a:
                print(f' - {k}: {b} -> {a}')
    save_json(TARGET, new)
    print('Applied preset to', TARGET)

if __name__ == '__main__':
    main()
