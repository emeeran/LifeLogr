import { ref, computed } from 'vue'

export function useCalendar() {
  const today = new Date()
  const year = ref(today.getFullYear())
  const month = ref(today.getMonth() + 1) // 1-based

  const monthNames = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
  ]
  const dayNames = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']

  const monthLabel = computed(() => `${monthNames[month.value - 1]} ${year.value}`)

  interface CalendarDay {
    date: number
    dateStr: string
    isCurrentMonth: boolean
  }

  const grid = computed<CalendarDay[]>(() => {
    const firstDay = new Date(year.value, month.value - 1, 1)
    let startWeekday = firstDay.getDay() // 0=Sun
    startWeekday = startWeekday === 0 ? 6 : startWeekday - 1 // convert to Mo=0

    const daysInMonth = new Date(year.value, month.value, 0).getDate()
    const daysInPrevMonth = new Date(year.value, month.value - 1, 0).getDate()

    const days: CalendarDay[] = []

    // Previous month's trailing days
    for (let i = startWeekday - 1; i >= 0; i--) {
      const d = daysInPrevMonth - i
      const m = month.value === 1 ? 12 : month.value - 1
      const y = month.value === 1 ? year.value - 1 : year.value
      days.push({ date: d, dateStr: `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`, isCurrentMonth: false })
    }

    // Current month
    for (let d = 1; d <= daysInMonth; d++) {
      days.push({ date: d, dateStr: `${year.value}-${String(month.value).padStart(2, '0')}-${String(d).padStart(2, '0')}`, isCurrentMonth: true })
    }

    // Next month's leading days
    const remaining = 42 - days.length // 6 rows x 7 cols
    for (let d = 1; d <= remaining; d++) {
      const m = month.value === 12 ? 1 : month.value + 1
      const y = month.value === 12 ? year.value + 1 : year.value
      days.push({ date: d, dateStr: `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`, isCurrentMonth: false })
    }

    return days
  })

  function prevMonth() {
    if (month.value === 1) { month.value = 12; year.value-- }
    else month.value--
  }

  function nextMonth() {
    if (month.value === 12) { month.value = 1; year.value++ }
    else month.value++
  }

  function goToday() {
    const now = new Date()
    year.value = now.getFullYear()
    month.value = now.getMonth() + 1
  }

  return { year, month, grid, dayNames, monthLabel, prevMonth, nextMonth, goToday }
}
