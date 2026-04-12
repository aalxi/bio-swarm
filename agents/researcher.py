"""Researcher Agent — Tavily-powered web search & scraping.

Uses GPT-5.4 mini to plan search queries, then executes them via Tavily.
Saves all raw results to workspace/raw_research/ and returns the
Agent Return Contract dict to the Supervisor.
"""

import json
from openai import OpenAI
from tools.tavily_tool import search_web, extract_url
from tools.file_tool import save_json
from tools.token_tracker import track_call

_client = None


def _get_openai_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


SEARCH_PLANNER_SYSTEM_PROMPT = """\
You are a search-query planner for a biology research pipeline.
Given the user's input and the pipeline mode, produce 2-3 targeted web search queries.

For wet_lab mode:
- Focus on finding the paper's full text, methodology sections, and protocol details.
- Include queries targeting the specific organisms, reagents, and techniques mentioned.

For dry_lab mode:
- One query must target the paper's GitHub repository or code supplement.
- One query must target the paper itself for methodology and expected outputs.
- One query should look for requirements.txt, environment.yml, or setup instructions.

Return ONLY valid JSON with this exact structure:
{
  "queries": ["query1", "query2", "query3"]
}
"""

EXTRACT_PLANNER_SYSTEM_PROMPT = """\
You are deciding which URLs from a set of search results deserve full-page extraction.
Pick the top 2 most relevant URLs — the ones most likely to contain the complete methodology,
protocol details, or (for dry_lab) the code repository page.

Return ONLY valid JSON with this exact structure:
{
  "urls": [
    {"url": "https://...", "reason": "one sentence explaining why"},
    {"url": "https://...", "reason": "one sentence explaining why"}
  ]
}
If fewer than 2 URLs are relevant, return only the relevant ones.
If none of the URLs are relevant, return:
{
  "urls": []
}
"""


def _plan_queries(user_input: str, mode: str) -> list[str]:
    """Ask GPT-5.4 mini to generate targeted search queries."""
    response = _get_openai_client().chat.completions.create(
        model="gpt-5.4-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SEARCH_PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Mode: {mode}\nUser input: {user_input}"},
        ],
    )
    track_call("researcher", response)
    data = json.loads(response.choices[0].message.content)
    return data.get("queries", [])


def _pick_extraction_urls(results: list[dict], mode: str) -> list[str]:
    """Ask GPT-5.4 mini which URLs deserve full extraction (top 2)."""
    summaries = []
    for r in results:
        summaries.append({"url": r.get("url"), "title": r.get("title"), "snippet": r.get("content", "")[:300]})

    response = _get_openai_client().chat.completions.create(
        model="gpt-5.4-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": EXTRACT_PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Mode: {mode}\nSearch results:\n{json.dumps(summaries, indent=2)}"},
        ],
    )
    track_call("researcher", response)
    data = json.loads(response.choices[0].message.content)
    urls_list = data.get("urls", [])
    return [entry["url"] for entry in urls_list if entry.get("url")]


def researcher_agent(user_input: str, mode: str, task_id: str) -> dict:
    """Run the Researcher Agent pipeline.

    1. GPT-5.4 mini plans 2-3 search queries based on user_input and mode.
    2. Executes each query via Tavily search_web().
    3. GPT-5.4 mini picks the best URL for full extraction.
    4. Extracts full page content via Tavily extract_url().
    5. Saves all raw results to workspace/raw_research/.

    Returns the Agent Return Contract dict.
    """
    output_files = []
    all_results = []
    all_sources = []

    # Step 1: Plan search queries
    try:
        queries = _plan_queries(user_input, mode)
    except Exception as e:
        return {
            "status": "error",
            "output_files": [],
            "message": "Failed to plan search queries",
            "retry_count": 0,
            "error_detail": str(e),
        }

    if not queries:
        queries = [user_input]

    # Step 2: Execute each query
    for i, query in enumerate(queries):
        try:
            results = search_web(query)
        except RuntimeError as e:
            return {
                "status": "error",
                "output_files": output_files,
                "message": f"Tavily search failed on query: {query}",
                "retry_count": 0,
                "error_detail": str(e),
            }

        # If zero results, retry once with a broader query
        if not results:
            broader_query = f"{user_input} biology protocol methodology"
            try:
                results = search_web(broader_query)
            except RuntimeError as e:
                return {
                    "status": "error",
                    "output_files": output_files,
                    "message": f"Tavily retry search failed on broader query: {broader_query}",
                    "retry_count": 1,
                    "error_detail": str(e),
                }

            if not results:
                return {
                    "status": "error",
                    "output_files": output_files,
                    "message": "No results found even after retry with broader query",
                    "retry_count": 1,
                    "error_detail": f"Queries attempted: {json.dumps([query, broader_query])}",
                }

        # Collect sources from each result
        for r in results:
            url = r.get("url")
            if url:
                all_sources.append(url)

        all_results.extend(results)

        # Save search results per query (strip raw_content to reduce token usage)
        clean_results = [
            {
                "url": r.get("url"),
                "title": r.get("title"),
                "content": r.get("content"),
                "score": r.get("score"),
            }
            for r in results
        ]
        search_file = f"workspace/raw_research/{task_id}_search_{i}.json"
        save_json({"query": query, "results": clean_results, "sources": [r.get("url") for r in results]}, search_file)
        output_files.append(search_file)

    # Step 3: Pick the best URLs for full extraction (top 2)
    extraction_urls = []
    try:
        extraction_urls = _pick_extraction_urls(all_results, mode)
    except Exception:
        # Non-fatal — we still have search results saved
        pass

    # Step 4: Extract full page content from the top URLs
    for idx, ext_url in enumerate(extraction_urls):
        try:
            full_content = extract_url(ext_url)
            extract_file = f"workspace/raw_research/{task_id}_extracted_{idx}.json"
            save_json({
                "source_url": ext_url,
                "raw_content": full_content,
            }, extract_file)
            output_files.append(extract_file)
        except RuntimeError:
            # Non-fatal — search results are still usable
            pass

    # Step 5: Save a combined summary file with all sources for downstream agents
    combined_file = f"workspace/raw_research/{task_id}_combined.json"
    save_json({
        "task_id": task_id,
        "mode": mode,
        "user_input": user_input,
        "queries": queries,
        "all_sources": list(set(all_sources)),
        "result_count": len(all_results),
        "extraction_urls": extraction_urls,
        "output_files": output_files,
    }, combined_file)
    output_files.append(combined_file)

    return {
        "status": "success",
        "output_files": output_files,
        "message": f"Research complete: {len(queries)} queries, {len(all_results)} results, {len(all_sources)} unique sources",
        "retry_count": 0,
        "error_detail": None,
    }
