def context_recall(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    relevant = set(relevant_ids)

    if not relevant:
        return 1.0

    return len(relevant.intersection(retrieved_ids)) / len(relevant)


def context_precision(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    relevant = set(relevant_ids)
    precisions: list[float] = []
    relevant_seen = 0

    for position, item_id in enumerate(retrieved_ids, start=1):
        if item_id in relevant:
            relevant_seen += 1
            precisions.append(relevant_seen / position)

    if not precisions:
        return 0.0

    return sum(precisions) / len(precisions)
