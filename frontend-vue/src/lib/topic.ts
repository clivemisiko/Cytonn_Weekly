// The same number as MAX_TOPIC_CHARS in backend/src/cytonn_weekly/focus/review_run.py, which is the limit the API enforces.
export const MAX_TOPIC = 500;

/**
 * A Focus topic's length as the API counts it (clean_topic in focus/review_run.py): edge whitespace dropped, each run
 * of whitespace counted as one space, then characters counted as code points (an emoji is one, as in Python), which
 * is why this spreads the string instead of reading .length. The API stays the judge; this only keeps the form from
 * disagreeing with it.
 */
export function topicLength(topic: string): number {
  return [...topic.trim().replace(/\s+/g, " ")].length;
}
