import type { ChatResponse, MessageResponse } from "./types";

export function reconcileCompletedMessages(
  current: MessageResponse[],
  optimisticId: string,
  result: ChatResponse,
): MessageResponse[] {
  return [
    ...current.filter((item) => (
      item.id !== optimisticId
      && item.id !== result.user_message.id
      && item.id !== result.assistant_message.id
    )),
    result.user_message,
    result.assistant_message,
  ].sort((first, second) => first.sequence_no - second.sequence_no);
}
