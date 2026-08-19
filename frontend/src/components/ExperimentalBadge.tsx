interface ExperimentalBadgeProps {
  visible: boolean;
}

export function ExperimentalBadge({ visible }: ExperimentalBadgeProps) {
  if (!visible) {
    return null;
  }
  return (
    <span className="badge" data-testid="experimental-badge">
      experimental
    </span>
  );
}
