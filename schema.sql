-- Supabase 建表 SQL
-- 在 Supabase Dashboard -> SQL Editor 中执行

CREATE TABLE IF NOT EXISTS bird_records (
    id BIGSERIAL PRIMARY KEY,
    user_nickname TEXT NOT NULL,
    chinese_name TEXT NOT NULL DEFAULT '未知鸟类',
    english_name TEXT DEFAULT '',
    order_chinese TEXT DEFAULT '',
    family_chinese TEXT DEFAULT '',
    confidence TEXT DEFAULT 'low',
    score INTEGER DEFAULT 0,
    score_sharpness INTEGER DEFAULT 0,
    score_composition INTEGER DEFAULT 0,
    score_lighting INTEGER DEFAULT 0,
    score_background INTEGER DEFAULT 0,
    score_pose INTEGER DEFAULT 0,
    score_artistry INTEGER DEFAULT 0,
    score_comment TEXT DEFAULT '',
    identification_basis TEXT DEFAULT '',
    bird_description TEXT DEFAULT '',
    shoot_date TEXT DEFAULT '',
    thumbnail_base64 TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 索引：按用户查询历史记录
CREATE INDEX IF NOT EXISTS idx_bird_records_user ON bird_records (user_nickname, created_at DESC);

-- 索引：按鸟种统计
CREATE INDEX IF NOT EXISTS idx_bird_records_species ON bird_records (chinese_name);

-- 开启 RLS（行级安全策略）
ALTER TABLE bird_records ENABLE ROW LEVEL SECURITY;

-- 允许匿名用户插入和查询（通过 anon key）
DROP POLICY IF EXISTS "允许所有人插入记录" ON bird_records;
CREATE POLICY "允许所有人插入记录" ON bird_records
    FOR INSERT WITH CHECK (true);

DROP POLICY IF EXISTS "允许所有人查询记录" ON bird_records;
CREATE POLICY "允许所有人查询记录" ON bird_records
    FOR SELECT USING (true);

DROP POLICY IF EXISTS "允许所有人删除记录" ON bird_records;
CREATE POLICY "允许所有人删除记录" ON bird_records
    FOR DELETE USING (true);
