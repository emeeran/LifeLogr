<template>
  <div class="space-y-6">
    <!-- Hero / unified sync -->
    <section class="rounded-xl border border-zinc-200 dark:border-zinc-700 p-5">
      <h2 class="text-lg font-semibold">Google Sync</h2>
      <p class="text-sm text-zinc-500 dark:text-zinc-400 mt-1">
        Sync Gmail (IMAP), Google Calendar and Google Tasks in one go. Mail stays on its existing
        IMAP connection; Calendar &amp; Tasks sync two-way.
      </p>
      <button
        class="mt-4 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium px-4 py-2 disabled:opacity-50"
        :disabled="syncingAll"
        @click="onSyncAll"
      >
        {{ syncingAll ? "Syncing…" : "Sync everything now" }}
      </button>
    </section>

    <!-- Calendar + Tasks connection -->
    <section class="rounded-xl border border-zinc-200 dark:border-zinc-700 p-5 space-y-4">
      <div class="flex items-center justify-between gap-4">
        <div>
          <h3 class="font-medium">Calendar &amp; Tasks</h3>
          <p class="text-xs text-zinc-500 dark:text-zinc-400">
            {{ status?.connected ? `Connected as ${status.google_email ?? "Google account"}` : "Not connected" }}
          </p>
        </div>
        <button
          v-if="!status?.connected"
          class="rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-3 py-1.5"
          @click="onConnect"
        >
          Connect Google
        </button>
        <button
          v-else
          class="rounded-lg border border-zinc-300 dark:border-zinc-600 text-sm px-3 py-1.5"
          :disabled="syncing"
          @click="onSync"
        >
          {{ syncing ? "Syncing…" : "Sync now" }}
        </button>
      </div>

      <template v-if="status?.connected">
        <div class="flex flex-col gap-2 text-sm">
          <label class="flex items-center gap-2">
            <input type="checkbox" :checked="status.calendar_enabled" @change="toggle('calendar_enabled', ($event.target as HTMLInputElement).checked)" />
            Calendar sync
          </label>
          <label class="flex items-center gap-2">
            <input type="checkbox" :checked="status.tasks_enabled" @change="toggle('tasks_enabled', ($event.target as HTMLInputElement).checked)" />
            Tasks sync
          </label>
        </div>

        <p v-if="status.last_synced_at" class="text-xs text-zinc-500 dark:text-zinc-400">
          Last sync: {{ formatTime(status.last_synced_at) }}
        </p>
        <p v-if="status.last_sync_error" class="text-xs text-red-500">
          Last error: {{ status.last_sync_error }}
        </p>

        <button class="text-xs text-zinc-500 hover:text-red-500 underline" @click="onDisconnect">
          Disconnect
        </button>
      </template>
    </section>

    <p class="text-xs text-zinc-400">
      The OAuth client must be a Test user app with Calendar + Tasks scopes; connect runs on port
      18765 (the OAuth redirect port).
    </p>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { googleSyncApi, type GoogleSyncStatus } from "../../../api/googleSync";

const emit = defineEmits<{ (e: "toast", type: "success" | "error", msg: string): void }>();

const status = ref<GoogleSyncStatus | null>(null);
const syncing = ref(false);
const syncingAll = ref(false);

async function load() {
  try {
    status.value = await googleSyncApi.getStatus();
  } catch (e) {
    /* ignore — shown as not connected */
  }
}

async function onConnect() {
  try {
    const { auth_url } = await googleSyncApi.getAuthUrl();
    window.open(auth_url, "_blank");
    emit("toast", "success", "Complete the Google sign-in, then return here");
  } catch (e) {
    emit("toast", "error", `Connect failed: ${(e as Error).message}`);
  }
}

async function onSync() {
  syncing.value = true;
  try {
    await googleSyncApi.sync();
    emit("toast", "success", "Google sync complete");
  } catch (e) {
    emit("toast", "error", `Sync failed: ${(e as Error).message}`);
  } finally {
    syncing.value = false;
    await load();
  }
}

async function onSyncAll() {
  syncingAll.value = true;
  try {
    await googleSyncApi.syncAll();
    emit("toast", "success", "Mail + Calendar + Tasks synced");
  } catch (e) {
    emit("toast", "error", `Sync all failed: ${(e as Error).message}`);
  } finally {
    syncingAll.value = false;
    await load();
  }
}

async function toggle(key: "calendar_enabled" | "tasks_enabled", value: boolean) {
  try {
    await googleSyncApi.setToggles({ [key]: value });
    await load();
  } catch (e) {
    emit("toast", "error", `Toggle failed: ${(e as Error).message}`);
  }
}

async function onDisconnect() {
  try {
    await googleSyncApi.disconnect();
    emit("toast", "success", "Google disconnected");
  } catch (e) {
    emit("toast", "error", `Disconnect failed: ${(e as Error).message}`);
  } finally {
    await load();
  }
}

function formatTime(iso: string) {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

onMounted(load);
</script>
