import streamlit as st
from blog_planning_agent import chatbot,extract_pointer
import uuid

import streamlit as st

st.title(":rainbow[blog_planning_agent]")

if "thread_id" not in st.session_state:
    thread_id=str(uuid.uuid4())
    st.session_state["thread_id"]=[]
    st.session_state["thread_id"].extend(extract_pointer())

if "conv_hist" not in st.session_state:
    st.session_state["conv_hist"]=[]

if "curr_thread_id" not in st.session_state:
    st.session_state["curr_thread_id"]=None


def load_conv(thread_id):
    state = chatbot.get_state(config={'configurable': {"thread_id": thread_id}})
    return state.values

response=None
#==========================================SIDEBAR============================================

st.sidebar.title("GENERATE YOUR BLOG")
user_input= st.sidebar.text_area("Topic:")
if st.sidebar.button("Generate", type="primary") and user_input.strip().lower():
    user_input=user_input.strip().lower()
    thread_id=str(uuid.uuid4())
    config={'configurable': {"thread_id": thread_id}}
    st.session_state["thread_id"].append(thread_id)

    # Create placeholders for real-time updates
    progress_placeholder = st.empty()
    status_placeholder = st.empty()

    # Stream the workflow execution
    final_state = None
    try:
        for state_dict in chatbot.stream(
            {"Topic": user_input, "evidence_pack": []},
            config=config,
            stream_mode="values"
        ):
            final_state = state_dict

            # Update progress indicator in real-time
            with progress_placeholder.container():
                st.header("⚡ Generation Progress")

                # Determine what stage we're currently in
                has_router = state_dict.get("routerDecision") is not None
                has_research = state_dict.get("evidence_pack") and len(state_dict.get("evidence_pack", [])) > 0
                has_plan = state_dict.get("plan") is not None
                has_sections = state_dict.get("sections") and len(state_dict.get("sections", [])) > 0
                has_final = state_dict.get("final") is not None

                # Current stage detection
                current_stage = "Unknown"
                if not has_router:
                    current_stage = "Initializing..."
                elif has_router and not has_research and not state_dict.get("routerDecision").need_research:
                    current_stage = "Routing (Closed Book - No Research Needed)"
                elif has_router and not has_research and state_dict.get("routerDecision").need_research:
                    current_stage = "Routing (Research Needed) → Researching..."
                elif has_research and not has_plan:
                    current_stage = "Research Complete → Planning..."
                elif has_plan and not has_sections:
                    current_stage = "Planning Complete → Writing Sections..."
                elif has_sections and not has_final:
                    current_stage = "Writing Sections → Finalizing..."
                elif has_final:
                    current_stage = "Generation Complete!"

                # Define stages
                stages = [
                    ("Router", has_router),
                    ("Research", has_research),
                    ("Planning", has_plan),
                    ("Writing", has_sections),
                    ("Complete", has_final)
                ]

                # Create progress display
                progress_cols = st.columns(len(stages))
                for i, (stage_name, is_complete) in enumerate(stages):
                    with progress_cols[i]:
                        if is_complete:
                            st.success(f"✅ {stage_name}")
                        elif stage_name == current_stage.split()[0] and "→" not in current_stage:
                            # Current stage being worked on
                            st.info(f"🔄 {stage_name}")
                        elif i > 0 and stages[i-1][1] and not is_complete:
                            # About to start this stage (previous complete, current not)
                            st.info(f"🔄 {stage_name}")
                        else:
                            st.empty()  # Future stage

                st.caption(f"Status: {current_stage}")

    except Exception as e:
        status_placeholder.error(f"Error during generation: {str(e)}")
        final_state = None

    # Store the final result
    if final_state is not None:
        response = final_state
        st.session_state["curr_thread_id"]=thread_id
    else:
        response = None
st.sidebar.divider()
st.sidebar.subheader("Conversation History")
for thread in st.session_state["thread_id"]:
    state=load_conv(thread)
    plan=state.get("plan",[]) if state else None
    title = str(plan.blog_title) if plan else thread[:8]
    if st.sidebar.button(title,key=thread):
        st.session_state["curr_thread_id"]=thread

#==========================================BODY=================================================
if st.session_state["curr_thread_id"] is not None:

    response=load_conv(st.session_state["curr_thread_id"])

if response:
    tab_blog, tab_planning, tab_logs,research = st.tabs(["Blog", "Planning", "Logs","research"])

    with tab_blog:
        if response:
            st.header(response["plan"].blog_title)
            st.write(response["final"])
            st.download_button(
                label="⬇️ Download Blog",
                data=response["final"],
                file_name=f"{response['plan'].blog_title}.md",
                mime="text/markdown"
            )
        else:
            st.error("some thing went wrong")

    with tab_planning:
    

        if response:
            # Show final execution summary
            st.header("Planning Section")
            router_decision = response.get("routerDecision")
            has_research_attempted = router_decision is not None and router_decision.need_research
            has_research_completed = bool(response.get("evidence_pack"))
            has_planning_completed = bool(response.get("plan"))
            has_writing_completed = bool(response.get("sections") and len(response.get("sections", [])) > 0)
            has_final_completed = bool(response.get("final"))

            mode = router_decision.mode if router_decision else "unknown"

            # Define what each stage represents
            stages = [
                ("Router", True),  # Router always runs
                ("Research", has_research_attempted),  # Research was attempted if needed
                ("Planning", has_planning_completed),
                ("Writing", has_writing_completed),
                ("Complete", has_final_completed)
            ]

            # Create status indicators for completed workflow
            status_cols = st.columns(len(stages))
            for i, (stage_name, was_executed) in enumerate(stages):
                with status_cols[i]:
                    if was_executed:
                        # Check if this stage actually has results (not just attempted)
                        if stage_name == "Research":
                            if has_research_completed:
                                st.success(f"✅ {stage_name}")
                            else:
                                st.warning(f"⚠️ {stage_name} (attempted)")
                        elif stage_name == "Router":
                            st.success(f"✅ {stage_name}")
                        else:
                            st.success(f"✅ {stage_name}")
                    else:
                        # Stage was skipped
                        if stage_name == "Research" and not has_research_attempted:
                            st.info(f"⏭️ {stage_name} (skipped)")
                        else:
                            st.empty()

            # Show execution details
            st.caption(f"Execution mode: {mode.replace('_', ' ').title()}")
            if has_research_attempted and not has_research_completed:
                st.caption("⚠️ Research was attempted but no sources were found")

            st.divider()

            # Show current plans if available
            if has_planning_completed:
                st.subheader("Blog Plan")
                plan = response["plan"]
                st.write(f"**Blog Title:** {plan.blog_title}")
                st.write(f"**Sections:** {len(plan.tasks)}")
                for i, task in enumerate(plan.tasks, 1):
                    with st.expander(f"Section {i}: {task.title}"):
                        st.write(f"**Goal:** {task.goal}")
                        st.write(f"**Target Words:** {task.target_words}")
                        st.write("**Bullets:**")
                        for bullet in task.bullets:
                            st.write(f"• {bullet}")
            elif has_writing_completed:
                st.subheader("Generated Sections")
                for i, section in enumerate(response.get("sections", []), 1):
                    with st.expander(f"Section {i}"):
                        st.markdown(section)
            else:
                st.write("Here are the current plans.")
        else:
            st.info("No data about planning is available")

    with tab_logs:
        st.header("Application Logs")
        st.write("Viewing recent logs...")
    with research:
        if response:
            evidence = response.get("evidence_pack", [])
            if evidence:
                st.header("Research Sources")
                for i, ev in enumerate(evidence, 1):
                    ev_d=ev.model_dump(exclude_unset=False)
                    with st.expander(f"Source {i}: {ev_d.get('title', 'No title')}"):
                        if ev_d.get('url'):
                            st.markdown(f"[Link to source]({ev_d['url']})")
                        if ev_d.get('published_at'):
                            st.caption(f"Published: {ev_d['published_at']}")
                        if ev_d.get('source'):
                            st.caption(f"Source: {ev_d['source']}")
                        if ev_d.get('snippet'):
                            st.write(ev_d['snippet'])
            else:
                st.info("No research sources were gathered for this topic.")
        else:
            st.info("No research data available.")
else:
    st.header("GENERATE YOUR BLOGS")
