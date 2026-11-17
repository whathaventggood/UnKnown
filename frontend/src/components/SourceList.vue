<script setup lang="ts">
import type {Source} from '../types'
import {safeUrl} from '../api'
defineProps<{sources:Source[]}>()
</script>
<template><div class="source-list"><article v-for="(source,i) in sources" :key="source.id"><span class="source-number">[{{i+1}}]</span><div><span class="tiny-label">{{source.platform}} · {{source.language}}</span><h3><a :href="safeUrl(source.url)" target="_blank" rel="noopener noreferrer">{{source.title}} ↗</a></h3><p>{{source.license||'许可信息未提供，请查看原始来源。'}}</p><small>采集于 {{source.fetched_at?new Date(source.fetched_at).toLocaleDateString('zh-CN'):'未记录'}}<span v-if="source.updated_at"> · 来源更新于 {{new Date(source.updated_at).toLocaleDateString('zh-CN')}}</span></small><details v-if="source.excerpt"><summary>查看允许用于解释的来源片段</summary><p class="source-excerpt">{{source.excerpt}}</p></details><p v-else class="privacy-note">未保存此来源的原始片段，不能将主题摘要归属为它的直接证据。</p></div></article></div></template>
