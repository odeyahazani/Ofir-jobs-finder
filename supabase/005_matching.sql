-- Additive matching metadata; existing feedback, scores and access rules are retained.
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS match_category TEXT DEFAULT 'unassessed'
 CHECK (match_category IN ('unassessed','priority','review','gap'));
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS match_version TEXT DEFAULT '';
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS match_details TEXT DEFAULT '{}';
