import pathlib

p = pathlib.Path(__file__).parent / "app.py"
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
# 保留前 1935 行（页脚 `)` 结束），删除后面所有残留重复代码
p.write_text("".join(lines[:1935]), encoding="utf-8")
print(f"Done. Kept {1935} lines, removed {len(lines) - 1935} lines.")
