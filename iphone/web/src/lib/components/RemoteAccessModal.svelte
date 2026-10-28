<script lang="ts">
  // HydraNest: sets or clears the phone's Tailscale address.
  import { untrack } from 'svelte';
  import { setRemoteAddress, type RemoteAccess } from '../api/remote';
  import { Submit } from '../submit.svelte';
  import ErrorLine from './ErrorLine.svelte';
  import Icon from './Icon.svelte';
  import Modal from './Modal.svelte';

  let { udid, name, current, onsaved, onclose }: {
    udid: string;
    name: string;
    current: RemoteAccess | null;
    onsaved: (access: RemoteAccess) => void;
    onclose: () => void;
  } = $props();

  let modal: Modal;
  // Seeded once at open: a poll must not reset what is being typed.
  let address = $state(untrack(() => current?.address ?? ''));
  const hadAddress = untrack(() => !!current?.address);
  const submit = new Submit('remote_save_failed');

  function close() {
    submit.abort();
    onclose();
  }

  async function save(value: string) {
    let saved: RemoteAccess | null = null;
    const ok = await submit.run(async (signal) => {
      saved = await setRemoteAddress(udid, value.trim(), signal);
    });
    if (ok && saved) {
      onsaved(saved);
      modal.close();
    }
  }
</script>

<Modal bind:this={modal} title={`Remote access for ${name}`} onclose={close}>
  <p class="py-3 text-sm text-base-content/70">
    At home the iPhone is found over Wi-Fi on its own. With its Tailscale address, HydraNest also reaches it
    away from home, while the iPhone is on a Wi-Fi network (any one) with Tailscale on. iOS doesn't allow it
    over cellular alone.
  </p>

  <form
    id="remote-access-form"
    onsubmit={(event) => {
      event.preventDefault();
      void save(address);
    }}
  >
    <label class="flex flex-col gap-1.5">
      <span class="label">Tailscale address</span>
      <input
        class="input w-full font-mono"
        placeholder="100.x.y.z or iphone.your-tailnet.ts.net"
        autocomplete="off"
        autocapitalize="off"
        spellcheck="false"
        bind:value={address}
        disabled={submit.busy}
        {@attach (node) => node.focus()}
      />
    </label>
    <p class="mt-1.5 text-xs text-base-content/60">
      The IP shown in the Tailscale app or admin console, or the full MagicDNS name
    </p>
  </form>

  <ErrorLine error={submit.failure} className="mt-3" />

  {#snippet actions()}
    {#if hadAddress}
      <button type="button" class="btn btn-ghost text-error mr-auto" disabled={submit.busy} onclick={() => save('')}>
        Turn off
      </button>
    {/if}
    <button type="button" class="btn btn-ghost" onclick={() => modal.close()}>Cancel</button>
    <button type="submit" form="remote-access-form" class="btn btn-primary" disabled={submit.busy || !address.trim()}>
      {#if submit.busy}
        <span class="loading loading-spinner loading-xs"></span>
        Saving…
      {:else}
        <Icon name="globe" size={15} /> Save
      {/if}
    </button>
  {/snippet}
</Modal>
