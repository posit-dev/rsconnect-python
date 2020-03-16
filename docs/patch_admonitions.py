import re

from os.path import abspath, dirname, join

block_pattern = re.compile(r'^> \*\*(\w+):\*\* ')
control = {
    'Important': 'warning'
}


def find_interesting_block(start=0):
    for line in range(start, len(lines)):
        match = block_pattern.match(lines[line])
        if match:
            return line, match.group(1)
    return -1, None


def get_block_text(start):
    first = lines[start]
    p = first.index(':** ') + 4
    result = ['    %s' % first[p:]]
    line = start + 1
    while line < len(lines) and lines[line].startswith('> '):
        result.append('    %s' % lines[line][2:])
        line = line + 1
    return result, line


def format_header(key):
    style = control[key] if key in control else key.lower()
    return '!!! %s "%s"\n' % (style, key)


directory = abspath(dirname(__file__))
source = join(dirname(directory), 'README.md')
target = join(directory, 'docs', 'index.md')

with open(source, 'r') as fd:
    lines = fd.readlines()

index, word = find_interesting_block()

while word:
    block, last = get_block_text(index)
    block.insert(0, format_header(word))
    lines[index:last] = block
    index, word = find_interesting_block(index + len(block))

with open(target, 'w') as fd:
    fd.writelines(lines)

print('%s generated.' % target)
