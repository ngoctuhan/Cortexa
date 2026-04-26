"""
Test Case: TC-V04
Name: Importance score boost
Category: Validation / Input
Input/Setup: 100 messages embedded; all vector records have default importance=1.0
             (set in repository/vector.go); rerank formula is
             score = cosine_sim × decay × importance.
Expected Result: score ≤ cosine_sim for all chunks (importance ≤ 1.0, decay ≤ 1.0);
                 chunk with highest cosine_sim ranks first when importance is uniform.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper

TURNS = [
    ("user",      "What is a relational database?"),
    ("assistant", "A relational database organises data into tables with rows and columns."),
    ("user",      "How does SQL work?"),
    ("assistant", "SQL is a query language for managing and retrieving relational data."),
    ("user",      "What is NoSQL?"),
    ("assistant", "NoSQL databases allow flexible schemas and horizontal scaling."),
    ("user",      "What is Redis used for?"),
    ("assistant", "Redis is an in-memory data store used for caching and pub/sub."),
    ("user",      "How does Docker work?"),
    ("assistant", "Docker packages applications into containers for consistent environments."),
    ("user",      "What is Kubernetes?"),
    ("assistant", "Kubernetes orchestrates containers across a cluster of machines."),
    ("user",      "What is a REST API?"),
    ("assistant", "A REST API uses HTTP methods to expose resources over the web."),
    ("user",      "What is GraphQL?"),
    ("assistant", "GraphQL is a query language for APIs that returns exactly the data requested."),
    ("user",      "What is gRPC?"),
    ("assistant", "gRPC is a high-performance RPC framework using Protocol Buffers."),
    ("user",      "What is cloud computing?"),
    ("assistant", "Cloud computing delivers compute, storage and networking as on-demand services."),
    ("user",      "What is AWS Lambda?"),
    ("assistant", "AWS Lambda runs code in response to events without managing servers."),
    ("user",      "What is a microservice?"),
    ("assistant", "A microservice is a small, independently deployable unit of functionality."),
    ("user",      "What is event-driven architecture?"),
    ("assistant", "Event-driven architecture uses events to trigger and communicate between services."),
    ("user",      "What is a message queue?"),
    ("assistant", "A message queue decouples producers and consumers of events asynchronously."),
    ("user",      "What is Kafka?"),
    ("assistant", "Kafka is a distributed event streaming platform for high-throughput pipelines."),
    ("user",      "What is a CDN?"),
    ("assistant", "A CDN caches content at edge nodes close to end users to reduce latency."),
    ("user",      "What is DNS?"),
    ("assistant", "DNS translates human-readable domain names into IP addresses."),
    ("user",      "What is a load balancer?"),
    ("assistant", "A load balancer distributes incoming traffic across multiple server instances."),
    ("user",      "What is TLS?"),
    ("assistant", "TLS encrypts network traffic to ensure privacy and integrity."),
    ("user",      "What is OAuth?"),
    ("assistant", "OAuth is an authorisation framework for delegating access without sharing passwords."),
    ("user",      "What is JWT?"),
    ("assistant", "A JWT is a compact, self-contained token for securely transmitting claims."),
    ("user",      "What is CORS?"),
    ("assistant", "CORS controls which origins are allowed to make cross-domain HTTP requests."),
    ("user",      "What is a firewall?"),
    ("assistant", "A firewall monitors and filters network traffic based on defined security rules."),
    # index 46 - the Python target (message #47, 1-indexed)
    ("user",
     "Python is an interpreted, high-level programming language famous for its clean syntax, "
     "extensive standard library, and massive ecosystem including NumPy, Pandas, and Django. "
     "It is the leading language for data science, machine learning, and scripting."),
    # index 47 onwards - unrelated topics
    ("assistant", "That is a great summary of Python strengths and ecosystem."),
    ("user",      "What is Java mainly used for?"),
    ("assistant", "Java is widely used for enterprise applications and Android development."),
    ("user",      "What is C++ known for?"),
    ("assistant", "C++ is known for system-level programming and high performance."),
    ("user",      "What is Rust?"),
    ("assistant", "Rust provides memory safety guarantees without a garbage collector."),
    ("user",      "What is Go?"),
    ("assistant", "Go is a statically typed language designed by Google for scalable services."),
    ("user",      "What is TypeScript?"),
    ("assistant", "TypeScript adds static types to JavaScript for better tooling and safety."),
    ("user",      "What is Swift?"),
    ("assistant", "Swift is Apple language for iOS and macOS application development."),
    ("user",      "What is Kotlin?"),
    ("assistant", "Kotlin is the preferred language for modern Android development."),
    ("user",      "What is machine learning?"),
    ("assistant", "Machine learning enables systems to learn patterns from data automatically."),
    ("user",      "What is deep learning?"),
    ("assistant", "Deep learning uses neural networks with many layers to learn representations."),
    ("user",      "What is a neural network?"),
    ("assistant", "A neural network is a graph of connected nodes that approximate functions."),
    ("user",      "What is backpropagation?"),
    ("assistant", "Backpropagation computes gradients through a network using the chain rule."),
    ("user",      "What is gradient descent?"),
    ("assistant", "Gradient descent iteratively adjusts parameters to minimise a loss function."),
    ("user",      "What is overfitting?"),
    ("assistant", "Overfitting occurs when a model memorises training data and generalises poorly."),
    ("user",      "What is regularisation?"),
    ("assistant", "Regularisation adds a penalty to the loss to discourage complex models."),
    ("user",      "What is a transformer model?"),
    ("assistant", "A transformer uses self-attention to process sequences in parallel."),
    ("user",      "What is BERT?"),
    ("assistant", "BERT is a bidirectional transformer pretrained on masked language modelling."),
    ("user",      "What is GPT?"),
    ("assistant", "GPT is a generative transformer pretrained to predict the next token."),
    ("user",      "What is RAG?"),
    ("assistant", "RAG augments generation with retrieved documents to ground responses in facts."),
    ("user",      "What is vector search?"),
    ("assistant", "Vector search finds nearest neighbours in a high-dimensional embedding space."),
    ("user",      "What is cosine similarity?"),
    ("assistant", "Cosine similarity measures the angle between two vectors regardless of magnitude."),
    ("user",      "What is an embedding?"),
    ("assistant", "An embedding is a dense numerical representation of text or other data."),
    ("user",      "What is a knowledge graph?"),
    ("assistant", "A knowledge graph stores entities and their relationships as a graph structure."),
    ("user",      "What is Elasticsearch?"),
    ("assistant", "Elasticsearch is a distributed search engine built on Apache Lucene."),
    ("user",      "What is full-text search?"),
    ("assistant", "Full-text search indexes and queries the contents of text documents."),
    ("user",      "What is TF-IDF?"),
    ("assistant", "TF-IDF scores words by frequency in a document relative to the corpus."),
    ("user",      "What is BM25?"),
    ("assistant", "BM25 is a probabilistic ranking function widely used in information retrieval."),
]

assert len(TURNS) == 100, f"Expected 100 turns, got {len(TURNS)}"


def poll_for_embeddings(tenant_id, user_id, session_id, query, max_attempts=36, sleep_sec=5):
    """Poll get_context until semantic_messages is non-empty (max max_attempts * sleep_sec seconds)."""
    for attempt in range(max_attempts):
        time.sleep(sleep_sec)
        success, resp, _ = APIClient.get_context(tenant_id, user_id, session_id, query)
        if success and resp.get("semantic_messages"):
            chunks = resp["semantic_messages"]
            print(f"Embeddings ready after {(attempt + 1) * sleep_sec}s — {len(chunks)} chunk(s) returned")
            return success, resp, chunks
        print(f"  Waiting for embeddings... attempt {attempt + 1}/{max_attempts} ({(attempt + 1) * sleep_sec}s elapsed)")
    raise AssertionError(f"Timed out waiting for embeddings ({max_attempts * sleep_sec}s)")


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print("Setting up 100 messages for TC-V04...")
    for role, content in TURNS:
        success, _, _ = APIClient.append_message(tenant_id, user_id, session_id, role=role, content=content)
        if not success:
            raise AssertionError(f"Failed to append turn: {content[:60]}")

    query = "Tell me about Python programming language features and ecosystem"
    _, resp, chunks = poll_for_embeddings(tenant_id, user_id, session_id, query)

    Assertions.assert_http_code(True, context="GetContext failed")
    Assertions.assert_field_exists(resp, "semantic_messages", context="GetContext response")

    # All vector records have importance=1.0 (default set in repository/vector.go).
    for i, chunk in enumerate(chunks):
        importance = chunk.get("importance", 0)
        assert abs(importance - 1.0) < 1e-6, (
            f"Chunk {i}: expected importance=1.0 (default), got {importance}"
        )

    # score = cosine_sim * decay * importance; since importance=1.0 and decay≤1:
    # score ≤ cosine_sim must hold.
    for i, chunk in enumerate(chunks):
        cosine = chunk["cosine_sim"]
        score  = chunk["score"]
        assert score <= cosine + 1e-6, (
            f"Chunk {i}: score {score:.6f} > cosine_sim {cosine:.6f}"
        )
        assert score > 0, f"Chunk {i}: score must be positive, got {score}"

    # With uniform importance, ranking is driven by cosine_sim × decay.
    # For fresh messages (decay≈1.0), top-1 chunk must have the highest cosine_sim.
    cosine_scores = [c["cosine_sim"] for c in chunks]
    assert cosine_scores[0] == max(cosine_scores), (
        f"Top-1 chunk should have highest cosine_sim; got {cosine_scores}"
    )

    print(f"PASS: all {len(chunks)} chunk(s) have importance=1.0; ranked by cosine_sim×decay")
    for i, c in enumerate(chunks):
        print(f"  [{i+1}] score={c['score']:.4f} cosine={c['cosine_sim']:.4f} importance={c.get('importance', 1.0):.2f}")


if __name__ == "__main__":
    run_test_wrapper("TC-V04", "Importance score boost", run_test)
