<script lang="ts">
  // HydraNest: the phone's Tailscale address, which netmuxd is told to reach
  // it at when Bonjour cannot see it (away from home).
  import { errMsg, isAbortError } from '../api/client';
  import { getRemoteAccess, setRemoteAddress, type RemoteAccess } from '../api/remote';
  import { now } from '../clock';
  import { errorText } from '../error-text';
  import { relativeTime } from '../format';
  import { Submit } from '../submit.svelte';
  import ErrorLine from './ErrorLine.svelte';
  import Icon from './Icon.svelte';
  import Pill from './Pill.svelte';

  let { udid }: { udid: string } = $props();

  // An attempt on an unreachable phone takes up to ~2 minutes server-side;
  // polling only picks the outcome up.
  const POLL_MS = 10_000;

  let access = $state<RemoteAccess | null>(null);
  let loadError = $state<string | null>(null);
  let address = $state('');
  // A poll must not overwrite what is being typed.
  let edited = $state(false);
  const submit = new Submit('remote_save_failed');

  $effect(() => {
    const id = udid;
    const ctrl = new AbortController();
    async function load() {
      try {
        const next = await getRemoteAccess(id, ctrl.signal);
        access = next;
        loadError = null;
        if (!edited) address = next.address;
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

  const dirty = $derived(address.trim() !== (access?.address ?? ''));
  const checked = $derived(access?.checkedAt ? relativeTime(access.checkedAt, $now) : null);

  async function save(value: string) {
    const ok = await submit.run(async (signal) => {
      access = await setRemoteAddress(udid, value.trim(), signal);
    });
    if (ok) {
      edited = false;
      address = access?.address ?? '';
    }
  }
</script>

<div class="card bg-base-100 shadow-sm">
  <div class="card-body gap-4 p-5">
    <div class="flex items-center justify-between gap-3">
      <h2 class="flex items-center gap-2 text-sm font-semibold">
        <Icon name="globe" size={15} />
        Remote access (Tailscale)
      </h2>
      {#if access?.state === 'attached'}
        <Pill tone="green" dot>Reachable</Pill>
      {:else if access?.state === 'failed'}
        <Pill tone="amber" dot>Not reachable</Pill>
      {:else if access?.state === 'waiting'}
        <Pill tone="slate" dot>Trying…</Pill>
      {:else if access}
        <Pill tone="slate">Off</Pill>
      {/if}
    </div>

    <p class="text-sm text-base-content/70">
      At home the iPhone is found over Wi-Fi on its own. With its Tailscale address here, HydraNest also
      reaches it away from home, while the iPhone is on a Wi-Fi network (any one) with Tailscale on.
      iOS doesn't allow it over cellular alone.
    </p>

    <form
      class="flex flex-col gap-2 sm:flex-row"
      onsubmit={(event) => {
        event.preventDefault();
        void save(address);
      }}
    >
      <input
        class="input w-full font-mono"
        placeholder="100.x.y.z or iphone.your-tailnet.ts.net"
        aria-label="Tailscale address"
        autocomplete="off"
        autocapitalize="off"
        spellcheck="false"
        bind:value={address}
        oninput={() => (edited = true)}
        disabled={submit.busy || !access}
      />
      <div class="flex gap-2">
        <button type="submit" class="btn btn-primary" disabled={submit.busy || !access || !dirty}>
          {#if submit.busy}
            <span class="loading loading-spinner loading-xs"></span>
          {/if}
          Save
        </button>
        {#if access?.address}
          <button type="button" class="btn btn-ghost" disabled={submit.busy} onclick={() => save('')}>
            Turn off
          </button>
        {/if}
      </div>
    </form>

    <ErrorLine error={submit.failure ?? loadError} />

    {#if access?.state === 'attached'}
      <p class="flex items-center gap-1.5 text-xs text-base-content/60">
        <Icon name="check" size={13} />
        Connected over the network{access.ip ? ` at ${access.ip}` : ''}{checked ? ` · checked ${checked}` : ''}
      </p>
    {:else if access?.state === 'failed' && access.error}
      <p class="flex items-center gap-1.5 text-xs text-base-content/60">
        <Icon name="info" size={13} />
        {errorText(access.error, 'remote_unreachable')}{checked ? ` · checked ${checked}` : ''}; tried again every minute
      </p>
    {:else if access?.state === 'waiting'}
      <p class="flex items-center gap-1.5 text-xs text-base-content/60">
        <span class="loading loading-spinner loading-xs"></span>
        Trying {access.address}…
      </p>
    {/if}
  </div>
</div>
