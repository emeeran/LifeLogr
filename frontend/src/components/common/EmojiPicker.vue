<script setup lang="ts">
import { ref } from "vue";
import { X, Search } from "lucide-vue-next";

const emit = defineEmits<{
  select: [emoji: string];
  close: [];
}>();

const categories = [
  { name: "Journal", emojis: ["📝", "💭", "✨", "🙏", "🩺", "💡"] },
  {
    name: "Smileys",
    emojis: [
      "😀",
      "😃",
      "😄",
      "😁",
      "😅",
      "😂",
      "🤣",
      "😊",
      "😇",
      "🙂",
      "🙃",
      "😉",
      "😌",
      "😍",
      "🥰",
      "😘",
      "😗",
      "😙",
      "😚",
      "😋",
      "😛",
      "😝",
      "😜",
      "🤪",
      "🤨",
      "🧐",
      "🤓",
      "😎",
      "🤩",
      "🥳",
      "😏",
      "😒",
      "😞",
      "😔",
      "😟",
      "😕",
      "🙁",
      "☹️",
      "😣",
      "😖",
      "😫",
      "😩",
      "🥺",
      "😢",
      "😭",
      "😤",
      "😠",
      "😡",
      "🤬",
      "🤯",
      "😳",
      "🥵",
      "🥶",
      "😱",
      "😨",
      "😰",
      "😥",
      "😓",
      "🤔",
      "🤭",
      "🤫",
      "🤥",
      "😶",
      "😐",
      "😑",
      "😬",
      "🙄",
      "😯",
      "😦",
      "😧",
      "😮",
      "😲",
      "🥱",
      "😴",
      "🤤",
      "😪",
      "😵",
      "🤐",
      "🥴",
      "🤢",
      "🤮",
      "🤧",
      "😷",
      "🤒",
      "🤕",
    ],
  },
  {
    name: "Hearts & Emotions",
    emojis: [
      "❤️",
      "🧡",
      "💛",
      "💚",
      "💙",
      "💜",
      "🖤",
      "🤍",
      "🤎",
      "💔",
      "❣️",
      "💕",
      "💞",
      "💓",
      "💗",
      "💖",
      "💘",
      "💝",
      "💟",
      "✨",
      "⭐",
      "🌟",
      "💫",
      "🔥",
      "💥",
      "💢",
      "💦",
      "💨",
      "💤",
      "💬",
      "💭",
    ],
  },
  {
    name: "Gestures",
    emojis: [
      "👍",
      "👎",
      "👌",
      "✌️",
      "🤞",
      "🤟",
      "🤘",
      "🤙",
      "👈",
      "👉",
      "👆",
      "👇",
      "✋",
      "🤚",
      "🖐️",
      "🖖",
      "👋",
      "🤙",
      "💪",
      "🙏",
      "👏",
      "🙌",
      "👐",
      "🤲",
      "🤝",
    ],
  },
  {
    name: "Nature",
    emojis: [
      "🌱",
      "🌿",
      "☘️",
      "🍀",
      "🍃",
      "🍂",
      "🍁",
      "🍄",
      "🐚",
      "🌹",
      "🌷",
      "🌼",
      "🌻",
      "🌞",
      "🌙",
      "⭐",
      "☁️",
      "🌧️",
      "⛈️",
      "❄️",
      "🌊",
      "🌈",
    ],
  },
  {
    name: "Activities",
    emojis: [
      "☕",
      "🍵",
      "🥤",
      "🍺",
      "🍷",
      "🍹",
      "🍕",
      "🍔",
      "🍟",
      "🍦",
      "🍰",
      "🍫",
      "🍎",
      "🍓",
      "🥑",
      "🥦",
    ],
  },
];

const searchQuery = ref("");

function selectEmoji(emoji: string) {
  emit("select", emoji);
}

function filterEmojis(emojis: string[]) {
  if (!searchQuery.value) return emojis;
  // This is a very basic search, in a real app we'd want names/keywords
  return emojis;
}
</script>

<template>
  <div
    class="flex flex-col w-64 h-80 bg-surface border border-border rounded-lg shadow-xl overflow-hidden"
  >
    <div
      class="flex items-center gap-2 p-2 border-b border-border bg-surface-hover/50"
    >
      <div class="relative flex-1">
        <Search
          :size="12"
          class="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted"
        />
        <input
          v-model="searchQuery"
          type="text"
          placeholder="Search emojis..."
          class="w-full bg-surface border border-border rounded px-7 py-1 text-xs text-text-primary outline-none focus:border-accent"
        />
      </div>
      <button
        @click="emit('close')"
        class="p-1 text-text-muted hover:text-text-primary transition-colors"
      >
        <X :size="14" />
      </button>
    </div>

    <div class="flex-1 overflow-y-auto p-2 space-y-3 custom-scrollbar">
      <div v-for="cat in categories" :key="cat.name">
        <div
          class="text-[10px] font-bold text-text-muted uppercase tracking-wider mb-1.5 px-1"
        >
          {{ cat.name }}
        </div>
        <div class="grid grid-cols-7 gap-1">
          <button
            v-for="emoji in filterEmojis(cat.emojis)"
            :key="emoji"
            @click="selectEmoji(emoji)"
            class="w-8 h-8 flex items-center justify-center text-lg hover:bg-surface-hover rounded transition-colors"
          >
            {{ emoji }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
