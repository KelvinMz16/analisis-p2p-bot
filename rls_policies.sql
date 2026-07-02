-- Habilitar RLS en todas las tablas
ALTER TABLE historical_prices ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE signal_log ENABLE ROW LEVEL SECURITY;

-- Políticas para historical_prices
CREATE POLICY "anon_insert" ON historical_prices FOR INSERT TO anon WITH CHECK (true);
CREATE POLICY "anon_select" ON historical_prices FOR SELECT TO anon USING (true);
CREATE POLICY "anon_update" ON historical_prices FOR UPDATE TO anon USING (true) WITH CHECK (true);
CREATE POLICY "anon_delete" ON historical_prices FOR DELETE TO anon USING (true);

-- Políticas para bot_config
CREATE POLICY "anon_insert" ON bot_config FOR INSERT TO anon WITH CHECK (true);
CREATE POLICY "anon_select" ON bot_config FOR SELECT TO anon USING (true);
CREATE POLICY "anon_update" ON bot_config FOR UPDATE TO anon USING (true) WITH CHECK (true);

-- Políticas para signal_log
CREATE POLICY "anon_insert" ON signal_log FOR INSERT TO anon WITH CHECK (true);
CREATE POLICY "anon_select" ON signal_log FOR SELECT TO anon USING (true);
CREATE POLICY "anon_update" ON signal_log FOR UPDATE TO anon USING (true) WITH CHECK (true);
