import streamlit as st
from main import app  

st.set_page_config(page_title="Agentic Researcher", layout="wide")

st.title("Autonomous Research Team")
st.markdown("This system uses **LangGraph** to orchestrate 4 agents: Planner, Researcher, Writer, and Critic.")

with st.sidebar:
    st.header("Settings")
    max_rev = st.number_input("Max Revisions", min_value=1, max_value=5, value=2)
    user_task = st.text_area("Research Topic:", height=150, 
        value="Research the latest advancements in Solid State Batteries in 2024.")
    run_btn = st.button("Start Research")

if run_btn:
    initial_state = {
        "task": user_task,
        "max_revisions": max_rev,
        "revision_number": 0,
        "content": []
    }
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🕵️‍♂️ Agent Workflow")
        status_container = st.container()
    with col2:
        st.subheader("📝 Final Report")
        report_container = st.empty()

    status_container.info("Initializing agents...")
    
    try:
        for step in app.stream(initial_state):
            for node_name, node_state in step.items():
                
                with status_container:
                    with st.expander(f"Agent: {node_name.upper()}", expanded=True):
                        if node_name == "planner":
                            st.write(f"**Plan:** {node_state.get('plan')}")
                        elif node_name == "researcher":
                            st.write(f"**Found Data:** {len(node_state.get('content', []))} sources.")
                        elif node_name == "writer":
                            st.write("**Drafting Report...**")
                            st.code(node_state.get('draft')[:500] + "...", language="markdown")
                        elif node_name == "critic":
                            critique = node_state.get('critique')
                            if "APPROVE" in critique:
                                st.success(f"Critique: {critique}")
                            else:
                                st.warning(f"Critique: {critique}")

                if 'draft' in node_state:
                    report_container.markdown(node_state['draft'])

    except Exception as e:
        st.error(f"An error occurred: {e}")