<script lang="ts">
  import { embedded } from '../lib/embedded';
  import { push } from 'svelte-spa-router';
  import Logo from '../lib/components/Logo.svelte';
  import ErrorLine from '../lib/components/ErrorLine.svelte';
  import { login } from '../lib/api/session';
  import { errMsg } from '../lib/api/client';

  let token = $state('');
  let busy = $state(false);
  let error = $state<string | null>(null);

  async function submit(event: Event) {
    event.preventDefault();
    const value = token.trim();
    if (!value || busy) return;
    busy = true;
    error = null;
    try {
      await login(value);
      push('/');
    } catch (err) {
      error = errMsg(err, 'sign_in_failed');
    } finally {
      busy = false;
    }
  }

</script>

<div class="flex min-h-screen items-center justify-center bg-base-200 px-4">
  <div class="card w-full max-w-sm border border-base-300 bg-base-100 shadow-sm">
    <form class="card-body gap-4" onsubmit={submit}>
      <div class="flex flex-col items-center gap-2 text-center">
        <Logo size={40} />
        <h1 class="text-lg font-semibold tracking-tight">Sign in to HydraNest iPhone</h1>
        <p class="text-sm text-base-content/60">
          Paste your Web UI token
        </p>
        {#if embedded}
          <p class="text-xs text-warning">
            HydraNest could not sign in to the iPhone service by itself: check IPHONE_AUTH_TOKEN in the stack.
          </p>
        {/if}
      </div>

      <input
        type="password"
        class="input w-full"
        placeholder="Web UI token"
        autocomplete="current-password"
        aria-label="Web UI token"
        bind:value={token}
        disabled={busy}
        {@attach (node) => node.focus()}
      />

      <ErrorLine {error} variant="alert" />

      <button type="submit" class="btn btn-primary" disabled={busy || !token.trim()}>
        {#if busy}<span class="loading loading-spinner loading-sm"></span>{/if}
        Sign in
      </button>
    </form>
  </div>
</div>
