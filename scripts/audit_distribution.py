#!/usr/bin/env python3
"""Scan release files for runtime data and concrete private identifiers."""
from pathlib import Path
import hashlib
import re
import sys
ROOT=Path(__file__).resolve().parents[1]
SKIP={'.git','.venv','node_modules','dist','__pycache__','.pytest_cache','.ruff_cache'}
BAD={'.db','.sqlite','.sqlite3','.zip','.gz','.pdf','.docx','.png','.jpg','.jpeg','.webp','.pyc'}
PATTERNS=[r'(?:libfile|Sentinel|appgprj|appgver)_[a-f0-9]{16,}',r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',r'gh[pousr]_[A-Za-z0-9]{30,}',r'(?:sk-proj-|sk-live-)[A-Za-z0-9_-]{20,}']
def main():
 errors=[];count=0
 for p in ROOT.rglob('*'):
  rel=p.relative_to(ROOT)
  if any(x in SKIP for x in rel.parts) or p.name.endswith('.tsbuildinfo'):continue
  if not p.is_file():continue
  count+=1
  if rel.as_posix()=="docs/images/dashboard-full-empty.jpg" and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()=="609f84e01539432a5347d06dbd58025bf9f34bc27c8ba69e77c24a98fa9e79d1":continue
  if rel.as_posix()=="docs/images/history-empty.jpg" and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()=="f9591652375950b43a2583045bcd03e654b4956ffc28515963a275b674c95d7a":continue
  if p.is_symlink() or rel.parts[0]=='data' or p.suffix.lower() in BAD or p.name in {'.env','RUNBOOK.md','RECOVERY_MANIFEST.json'}:errors.append(str(rel)+': forbidden artifact');continue
  try:s=p.read_text()
  except UnicodeError:errors.append(str(rel)+': binary');continue
  if any(re.search(pattern,s) for pattern in PATTERNS):errors.append(str(rel)+': identifier/secret')
 print('\n'.join(errors));print(f'{count} files; {len(errors)} findings')
 return bool(errors)
if __name__=='__main__':sys.exit(main())
