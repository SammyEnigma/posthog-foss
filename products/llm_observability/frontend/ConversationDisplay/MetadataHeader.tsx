import { LemonTag } from '@posthog/lemon-ui'
import classNames from 'classnames'
import { lowercaseFirstLetter } from 'lib/utils'

import { MetadataTag } from '../components/MetadataTag'

export function MetadataHeader({
    inputTokens,
    outputTokens,
    totalCostUsd,
    model,
    latency,
    className,
    isError,
    cacheReadTokens,
    cacheWriteTokens,
}: {
    inputTokens?: number
    outputTokens?: number
    cacheReadTokens?: number
    cacheWriteTokens?: number
    totalCostUsd?: number
    model?: string
    latency?: number
    isError?: boolean
    className?: string
}): JSX.Element {
    return (
        <div className={classNames('flex flex-wrap gap-2', className)}>
            {isError && <LemonTag type="danger">Error</LemonTag>}
            {typeof latency === 'number' && (
                <MetadataTag label="Latency">{`${Math.round(latency * 10e2) / 10e2} s of latency`}</MetadataTag>
            )}
            {typeof inputTokens === 'number' && typeof outputTokens === 'number' && (
                <MetadataTag label="Token usage">
                    {`${inputTokens} prompt tokens → ${outputTokens} completion tokens (∑ ${
                        inputTokens + outputTokens
                    })`}
                </MetadataTag>
            )}
            {typeof cacheReadTokens === 'number' && cacheReadTokens > 0 && (
                <MetadataTag label="Cache read">{`${cacheReadTokens} tokens`}</MetadataTag>
            )}
            {typeof cacheWriteTokens === 'number' && cacheWriteTokens > 0 && (
                <MetadataTag label="Cache write">{`${cacheWriteTokens} tokens`}</MetadataTag>
            )}
            {model && (
                <MetadataTag label="Model" textToCopy={lowercaseFirstLetter(model)}>
                    {model}
                </MetadataTag>
            )}
            {typeof totalCostUsd === 'number' && (
                <MetadataTag label="Total generation cost">{`$${Math.round(totalCostUsd * 10e6) / 10e6}`}</MetadataTag>
            )}
        </div>
    )
}
