// Browser-side Supabase client. Reads keys injected by Flask via the
// inline <script> tag in templates/base.html.
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const url = window.__PL__?.SUPABASE_URL;
const key = window.__PL__?.SUPABASE_ANON_KEY;

export const supabase = url && key ? createClient(url, key, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
    storageKey: 'pl-auth',
  },
}) : null;

export async function syncSessionToServer() {
  if (!supabase) return;
  const { data } = await supabase.auth.getSession();
  const session = data?.session;
  if (!session) return;
  await fetch('/auth/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      user: session.user,
      access_token: session.access_token,
      refresh_token: session.refresh_token,
    }),
  });
}

export async function signOut() {
  if (supabase) await supabase.auth.signOut();
  await fetch('/auth/logout', { method: 'POST' });
  window.location.href = '/';
}

// Keep server session in sync whenever the JS auth state changes.
if (supabase) {
  supabase.auth.onAuthStateChange(async (event) => {
    if (event === 'SIGNED_IN' || event === 'TOKEN_REFRESHED') {
      await syncSessionToServer();
    }
  });
}
