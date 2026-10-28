<script lang="ts">
  // HydraNest: the phone's Tailscale address, a settings row of the Backup
  // card. netmuxd is told to reach the phone there when Bonjour cannot see it
  // (away from home).
  import { errMsg, isAbortError } from '../api/client';
  import { getRemoteAccess, type RemoteAccess } from '../api/remote';
  import { now } from '../clock';
  import { errorText } from '../error-text';
  import { relativeTime } from '../format';
  import ErrorLine from './ErrorLine.svelte';
  import Icon from './Icon.svelte';
  import Pill from './Pill.svelte';
  import RemoteAccessModal from './RemoteAccessModal.svelte';

  let { udid, name }: { udid: string; name: string } = $props();

  // An attempt on an unreachable phone takes up to ~2 minutes server-side;
  // polling only picks the outcome up.
  const POLL_MS = 10_000;

  let access = $state<RemoteAccess | null>(null);
  let loadError = $state<string | null>(null);
  let editing = $state(false);

  $effect(() => {
    const id = udid;
    const ctrl = new AbortController();
    async function load() {
      try {
        access = await getRemoteAccess(id, ctrl.signal);
        loadError = null;
      } catch (err) {
        if (!isAbortError(err)) loadError = errMsg(err, 'remote_load_failed');
      }
    }
    void load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      clearInterval(timer);
      ctrl.abort();
    };
  });

  // $now ticks every 30 s, so a fresh check would otherwise read as future.
  const checked = $derived(access?.checkedAt ? relativeTime(access.checkedAt, Math.max($now, Date.now())) : null);
</script>

<div class="flex flex-wrap items-center justify-between gap-3 border-t border-base-300 pt-4">
  <div class="min-w-0">
    <p class="flex items-center gap-2 text-sm font-semibold">
      Remote access
      {#if access?.state === 'attached'}
        <Pill tone="green" dot>Reachable</Pill>
      {:else if access?.state === 'failed'}
        <Pill tone="amber" dot>Not reachable</Pill>
      {:else if access?.state === 'waiting'}
        <Pill tone="slate" dot>Trying…</Pill>
      {:else}
        <Pill tone="slate" dot>Off</Pill>
      {/if}
    </p>
    <p class="mt-0.5 text-xs text-base-content/60">
      {#if access?.address}
        <span class="text-base-content/80">Tailscale {access.address}</span> ·
        {#if access.state === 'attached'}
          connected{access.ip && access.ip !== access.address ? ` at ${access.ip}` : ''}{checked ? `, checked ${checked}` : ''}
        {:else if access.state === 'failed' && access.error}
          {errorText(access.error, 'remote_unreachable')}{checked ? `, checked ${checked}` : ''}
        {:else}
          trying…
        {/if}
      {:else}
        Backs up away from home too, through Tailscale, while the iPhone is on any Wi-Fi
      {/if}
    </p>
    <ErrorLine error={loadError} size="xs" className="mt-1" />
  </div>
  <button type="button" class="btn btn-ghost btn-sm" disabled={!access} onclick={() => (editing = true)}>
    <Icon name="globe" size={14} />
    {access?.address ? 'Change…' : 'Set up…'}
  </button>
</div>

<!-- Mounted fresh per open. -->
{#if editing}
  <RemoteAccessModal
    {udid}
    {name}
    current={access}
    onsaved={(saved) => (access = saved)}
    onclose={() => (editing = false)}
  />
{/if}
