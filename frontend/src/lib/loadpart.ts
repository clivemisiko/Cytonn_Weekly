import { ref, shallowRef } from "vue";

/** One read a page makes on load: what it got, or why it failed, kept apart so one failed read hides nothing else and its Try again repeats only it. */
export function usePart<T>(load: () => Promise<T>) {
  const value = shallowRef<T | null>(null);
  const problem = ref<string | null>(null);
  let generation = 0;
  /** True when this run's answer arrived and is the latest; false when it failed or a newer run or a reset came first. */
  async function run(): Promise<boolean> {
    const mine = ++generation;
    problem.value = null;
    try {
      const got = await load();
      if (mine !== generation) return false;
      value.value = got;
      return true;
    } catch (err) {
      if (mine === generation) problem.value = (err as Error).message;
      return false;
    }
  }
  function reset() {
    generation++;
    value.value = null;
    problem.value = null;
  }
  return { value, problem, run, reset };
}
