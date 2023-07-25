# %% [markdown]
# ## Doc default PT

# %%
doc_pt = '''THE CONTEXT：
```
{docs_strs}
```
Analysis if THE CONTEXT is relative to the question bellow. If the
context and the question are relative, generate the answer according the
content of the context; if not, ignore the context and generate an patient and meticulous answer for Chinese college students .
```
{query}
```
Don't tell me the relativity,  just give me the generated ANSWER:'''

# %% [markdown]
# ## Choice Question PT

# %%
choice_pt = '''下面的问题是一个选择题,请在返回的内容中不要给答案,不要要给具体的选项是什么,只是对选项做分析即可:
```
{query}
```'''

# %% [markdown]
# ## Global Default PT

# %%
default_pt='''您回复对象是中国大学生，请耐心细致的回答下面这个问题:
```
{query}
```'''

# %% [markdown]
# ## Single Router PT

# %%
if_else_router_pt = '''这是一个选择题吗？
```
{query}
```
如果是，就返回True;如果不是，就返回 False. Please give the result as a boolean value( "True" or "False"):'''

# %%
import os

from langchain.document_loaders import DirectoryLoader
from langchain.embeddings import OpenAIEmbeddings
from langchain.text_splitter import CharacterTextSplitter

print(os.path.abspath(os.path.curdir))

# %%
from langchain.vectorstores import Chroma


class HiEngine:
    def __init__(self, path="note/data/", chunk_size=700):
        loader = DirectoryLoader(path=path, glob="*.docx")

        # 加载文件夹中的所有txt类型的文件
        # 将数据转成 document 对象，每个文件会作为一个 document
        documents = loader.load()

        # 初始化加载器
        text_splitter = CharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=int(chunk_size * 0.2))
        # 切割加载的 document
        split_docs = text_splitter.split_documents(documents)
        ebd = OpenAIEmbeddings()
        self.vdb = Chroma.from_documents(embedding=ebd, documents=split_docs, persist_directory="note/data/vdb")

def prepare_engine(chunk_size=700):
    docsearch = Simi(split_docs)

    _filter = LLMChainFilter.from_llm(llm=OpenAI(temperature=0.0))
    __test_pt = PromptTemplate.from_template('''这是一个选择题吗？\n```\n{query}\n```\n 如果是，就返回True;如果不是，就返回 False. Please give the result as a boolean value( "True" or "False"):''')
    __llm=OpenAI(temperature=0.2)
    __llm=ChatOpenAI(model_name='gpt-3.5-turbo', temperature=0.6)
    default_pt = PromptTemplate.from_template('您回复对象是中国大学生，请耐心细致的回答下面这个问题:\n```\n{query}\n```')

    def handle(query, pt='''检索内容：\n```\n{docs_strs}\n```\n\n请基于以上内容，分析问题: \n```\n{query}\n```''',
               choice_pt='''下面的问题是一个选择题,请在返回的内容中不要给答案,不要要给具体的选项是什么,只是对选项做分析即可:\n```\n{query}\n```\n''',
               default_pt='您回复对象是中国大学生，请耐心细致的回答下面这个问题:\n```\n{query}\n```',
               similarity_threshold=0.85,
               squential_chain_cfg=[]):
        default_pt = PromptTemplate.from_template(default_pt)
        __pt = PromptTemplate.from_template(pt)
        __ques_pt = PromptTemplate.from_template(choice_pt)
        import json
        if json.loads(__llm.predict(__test_pt.format(query=query)).lower()):
            prompt = __ques_pt.format(query=query)
            return query, prompt, __llm.predict(prompt), []

        ds = [(d,s) for d, s in docsearch.similarity_search_with_score(query, k=141) if s > similarity_threshold][-3:]
        if ds:
            prompt = __pt.format(docs_strs='\n\n'.join([d.page_content for d,s in ds]), query=query)
            return query, prompt, __llm.predict(prompt), [(json.loads(d.json()), s) for d,s in ds]
        else:
            prompt = default_pt.format(query=query)
            return query, prompt, __llm.predict(prompt), []

    return handle

# %%
e = HiEngine()

# %%
res = e.vdb.similarity_search_with_relevance_scores("根据project部分的要求，以Challenges for freshmen and ways out为题写一段400字的conversation.")
print(res)


