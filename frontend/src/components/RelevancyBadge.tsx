interface Props {
  score: number
}

export function RelevancyBadge({ score }: Props) {
  const pct = Math.round(score * 100)

  let color = 'bg-gray-200'
  if (pct >= 75) color = 'bg-accent'
  else if (pct >= 50) color = 'bg-blue-300'
  else if (pct >= 25) color = 'bg-blue-200'

  return (
    <span
      className={`inline-block w-1.5 h-1.5 rounded-full ${color} flex-shrink-0`}
      title={`Relevancy: ${pct}%`}
    />
  )
}
