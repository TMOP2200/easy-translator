#!/bin/bash
# 跑全量测试，并核对「每个文件都真的在跑测试」——
# 只看退出码会漏掉假绿（pytest 风格的文件在没装 pytest 的环境里是零条测试、退出码 0）。
# 用法: bash tools/run_tests.sh
cd "$(dirname "$0")/.." || exit 1
py=.venv/Scripts/python.exe
ok=0
bad=0
for t in tests/test_*.py; do
    n=$(basename "$t")
    out=$(timeout 180 "$py" "$t" 2>&1)
    ran=$(printf '%s' "$out" | grep -oE "Ran [0-9]+ test" | head -1)
    if [ -z "$ran" ]; then
        echo "✗ $n  空跑（没有任何测试在跑）"
        bad=$((bad + 1))
    elif printf '%s' "$out" | grep -qE "FAILED|Traceback|AssertionError"; then
        echo "✗ $n  $ran（有失败）"
        printf '%s' "$out" | grep -E "^(FAIL|ERROR):" | head -3
        bad=$((bad + 1))
    else
        echo "✓ $n  $ran"
        ok=$((ok + 1))
    fi
done
echo "—— 通过 $ok 个文件，失败 $bad 个 ——"
[ "$bad" -eq 0 ]
