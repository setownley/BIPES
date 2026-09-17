"""Safety wiring checks for the BIPES Files tab on DevLink."""

from pathlib import Path


root = Path(__file__).resolve().parents[2]
source = (root / "ui" / "core" / "utils.js").read_text(encoding="utf-8")

list_start = source.index("  listFiles ()")
list_end = source.index("  run (file)", list_start)
assert "devLinkListFiles" in source[list_start:list_end]
assert "renderFileList" in source[list_start:list_end]

run_start = source.index("  run (file)")
run_end = source.index("  delete (file)", run_start)
run_block = source[run_start:run_end]
assert "devLinkReadFile" in run_block
assert "runProgram" in run_block
assert "endsWith('.py')" in run_block

delete_start = source.index("  delete (file)")
delete_end = source.index("  files_view (file)", delete_start)
delete_block = source[delete_start:delete_end]
assert "Bluetooth deletion is disabled" in delete_block

get_start = source.index("  get_file (src_fname)")
get_end = source.index("  get_file_webserial_", get_start)
get_block = source[get_start:get_end]
assert "devLinkReadFile" in get_block
assert "verified bytes" in get_block
assert "saveAs" in get_block
assert "updateSourceCode" in get_block

print("ALL PASS")
