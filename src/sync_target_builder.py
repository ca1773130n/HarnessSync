from __future__ import annotations

"""Per-target data filtering, transformation, and augmentation for sync.

Builds target-specific data by applying env-tagged filtering, sync tags,
inline annotations, transform rules, MCP routing/aliasing/ordering,
model routing, skill sync tags, and agent translation hints.
Extracted from SyncOrchestrator._build_target_data.
"""

from pathlib import Path

from src.source_reader import SourceReader
from src.sync_filter import filter_rules_for_target, filter_rules_for_env
from src.utils.logger import Logger


def build_target_data(
    adapter_data: dict,
    target: str,
    reader: SourceReader,
    project_dir: Path | None,
    harness_env: str | None,
    rules_have_tags: bool,
    rules_have_annotations: bool,
    ann_filter_cls,
    transform_engine,
    model_routing_hints,
    model_routing_summary: list[str],
    logger: Logger,
) -> dict:
    """Build target-specific data by applying per-target filtering and transforms.

    Args:
        adapter_data: Base adapter data dict
        target: Target harness name
        reader: SourceReader instance
        project_dir: Project root directory
        harness_env: Environment name for env-tagged section filtering
        rules_have_tags: Whether rules have sync tags
        rules_have_annotations: Whether rules have inline harness annotations
        ann_filter_cls: AnnotationFilter class (or None)
        transform_engine: TransformEngine instance (or None)
        model_routing_hints: Model routing hints (or None)
        model_routing_summary: List to append model routing messages to
        logger: Logger instance

    Returns:
        Filtered and transformed data dict for this target
    """
    target_data = dict(adapter_data)

    # Step 1: filter env-tagged sections
    if harness_env:
        target_data['rules'] = [
            {**r, 'content': filter_rules_for_env(r.get('content', ''), harness_env)}
            for r in adapter_data.get('rules', [])
            if isinstance(r, dict)
        ]

    # Step 2: filter per-target sync tags
    if rules_have_tags:
        rules_source = target_data.get('rules', adapter_data.get('rules', []))
        target_data['rules'] = [
            {**r, 'content': filter_rules_for_target(r.get('content', ''), target)}
            for r in rules_source
            if isinstance(r, dict)
        ]

    # Step 2b: filter inline harness annotations
    if rules_have_annotations and ann_filter_cls:
        try:
            ann_rules = target_data.get('rules', adapter_data.get('rules', []))
            ann_filtered = ann_filter_cls.filter_rules_for_target(ann_rules, target)
            if isinstance(ann_filtered, list):
                target_data['rules'] = ann_filtered
        except Exception:
            pass

    # Step 3: apply user-defined transform rules
    if transform_engine and transform_engine.has_rules():
        target_data['rules'] = transform_engine.apply_to_rules(
            target_data.get('rules', adapter_data.get('rules', [])), target
        )

    # Step 4: apply rule category tag filtering
    try:
        from src.rule_tagger import RuleTagger
        rule_tagger = RuleTagger(project_dir=project_dir)
        if rule_tagger.is_configured:
            target_data['rules'] = rule_tagger.filter_rules_list(
                target_data.get('rules', adapter_data.get('rules', [])), target
            )
    except Exception:
        pass

    # Per-harness override files
    override_content = reader.get_harness_override(target)
    if override_content:
        target_data['rules'] = list(target_data.get('rules', []))
        target_data['rules'].append({
            'path': f'CLAUDE.{target}.md',
            'content': override_content,
            'scope': 'project',
            'scope_patterns': [],
        })

    # Inline harness blocks
    try:
        inline_block = reader.get_inline_harness_block(target)
        if inline_block:
            target_data['rules'] = list(target_data.get('rules', []))
            target_data['rules'].append({
                'path': f'CLAUDE.md#harness:{target}',
                'content': inline_block,
                'scope': 'project',
                'scope_patterns': [],
            })
    except Exception:
        pass

    # MCP aliasing
    try:
        from src.mcp_aliasing import load_aliases, apply_aliases
        mcp_aliases = load_aliases(project_dir=project_dir)
        if mcp_aliases and target_data.get('mcp'):
            target_data['mcp'] = apply_aliases(
                target_data['mcp'], target, mcp_aliases
            )
    except Exception:
        pass

    # MCP routing
    try:
        from src.mcp_routing import McpRouter
        mcp_router = McpRouter(project_dir=project_dir)
        if mcp_router.is_configured and isinstance(target_data.get('mcp'), dict):
            dropped = mcp_router.dropped_servers(target_data['mcp'], target)
            target_data['mcp'] = mcp_router.filter_for_target(
                target_data['mcp'], target
            )
            for dropped_srv in dropped:
                logger.warn(
                    f"MCP routing: '{dropped_srv}' not synced to {target} "
                    f"(per .harnesssync/mcp_routing.json)"
                )
    except Exception:
        pass

    # MCP dependency ordering
    try:
        from src.mcp_dependency_resolver import MCPDependencyResolver
        mcp_data = target_data.get('mcp')
        if isinstance(mcp_data, dict) and len(mcp_data) > 1:
            dep_resolver = MCPDependencyResolver()
            ordered_mcp = dep_resolver.apply_ordering_to_dict(mcp_data)
            target_data['mcp'] = ordered_mcp
            cycle_warnings = dep_resolver.check_cycles(mcp_data)
            for cw in cycle_warnings:
                logger.warn(
                    f"{target}: MCP dependency cycle detected for '{cw}' "
                    "-- startup order may be incorrect"
                )
    except Exception:
        pass

    # Model routing
    try:
        if model_routing_hints and not model_routing_hints.is_empty:
            from src.model_routing import ModelRoutingAdapter as _MRA
            translated = _MRA().translate_for_target(model_routing_hints, target)
            if translated and translated.default_model:
                settings = target_data.get('settings')
                if isinstance(settings, dict):
                    if 'model' not in settings:
                        settings['model'] = translated.default_model
                        model_routing_summary.append(
                            f"  {target}: model -> {translated.default_model}"
                        )
    except Exception:
        pass

    # Skill sync tags
    try:
        from src.skill_sync_tags import filter_skills_for_target as _fst
        skills_raw = target_data.get('skills')
        if isinstance(skills_raw, dict) and skills_raw:
            target_data['skills'] = _fst(skills_raw, target)
    except Exception:
        pass

    # Agent sync tags (parallel to skill sync tags — filters before translation)
    try:
        from src.skill_sync_tags import filter_agents_for_target as _filter_agents
        agents_for_tag_check = target_data.get('agents')
        if isinstance(agents_for_tag_check, dict) and agents_for_tag_check:
            target_data['agents'] = _filter_agents(agents_for_tag_check, target)
    except Exception:
        pass

    # Agent translation hints
    try:
        from src.skill_translator import inject_agent_translation_hints
        import tempfile as _tempfile
        agents_raw = target_data.get('agents')
        if isinstance(agents_raw, dict) and agents_raw:
            annotated_agents: dict = {}
            tmp_dir = Path(_tempfile.mkdtemp(prefix="harnesssync_hints_"))
            for aname, apath in agents_raw.items():
                try:
                    apath_obj = Path(apath)
                    if not apath_obj.exists():
                        annotated_agents[aname] = apath
                        continue
                    orig_content = apath_obj.read_text(encoding="utf-8")
                    hinted_content = inject_agent_translation_hints(
                        orig_content, aname, target
                    )
                    if hinted_content != orig_content:
                        tmp_path = tmp_dir / f"{aname}.md"
                        tmp_path.write_text(hinted_content, encoding="utf-8")
                        annotated_agents[aname] = tmp_path
                    else:
                        annotated_agents[aname] = apath
                except Exception:
                    annotated_agents[aname] = apath
            target_data['agents'] = annotated_agents
    except Exception:
        pass

    return target_data
