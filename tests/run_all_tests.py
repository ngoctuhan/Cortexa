import os
import subprocess
import sys
import time

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(TESTS_DIR, "scripts")

def main():
    print("============================================================")
    print("🚀 BẮT ĐẦU CHẠY AUTOMATION TEST SUITE TỪ THƯ MỤC SCRIPTS")
    print("============================================================")
    
    scripts = [f for f in os.listdir(SCRIPTS_DIR) if f.endswith('.py') and f.startswith('TC-')]
    scripts.sort()
    
    passed = 0
    failed = 0
    
    for script in scripts:
        script_path = os.path.join(SCRIPTS_DIR, script)
        tc_id = script.replace('.py', '')
        
        start_time = time.time()
        env = os.environ.copy()
        env["PYTHONPATH"] = TESTS_DIR + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(["python3", script_path], capture_output=True, text=True, env=env)
        latency = (time.time() - start_time) * 1000
        
        if result.returncode == 0:
            print(f"✅ PASS | {tc_id} ({latency:.2f}ms)")
            passed += 1
        else:
            print(f"❌ FAIL | {tc_id} ({latency:.2f}ms)")
            out = result.stdout.strip().split('\\n')[-1] if result.stdout else result.stderr.strip()
            print(f"   -> Detail: {out}")
            failed += 1

    print("============================================================")
    print("📊 BÁO CÁO KẾT QUẢ TEST (TEST REPORT)")
    print(f"✅ PASSED: {passed}")
    print(f"❌ FAILED: {failed}")
    print("============================================================")

if __name__ == "__main__":
    main()
