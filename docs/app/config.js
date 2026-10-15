// Public settings for the hosted app. The publishable key is safe in a browser:
// row-level security limits every signed-in user to their own rows and files.
// Secrets (Anthropic key, mailbox password, Supabase secret key) live only in the worker.
window.CLAIMBACK = {
  supabaseUrl: "https://wptacpjwhzwquyhszchw.supabase.co",
  supabaseKey: "sb_publishable_bKavixJB5OVprZekxWtKOA_GwYrMnmS",
  apiUrl: "https://claimback--claimback-api.us-east.modal.run",
};
