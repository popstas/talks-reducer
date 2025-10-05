import sys
spec_file = sys.argv[1]
with open(spec_file, 'r') as f:
    content = f.read()

# Add binary filter before EXE definition
filter_code = '''
# Filter out CUDA DLLs
cuda_patterns = ['cublas', 'cufft', 'curand', 'cusolver', 'cusparse', 'cudnn', 'nvcuda', 'nvrtc', 'cublasLt', 'cuTENSOR']
a.binaries = [x for x in a.binaries if not any(pattern.lower() in x[0].lower() for pattern in cuda_patterns)]

'''

# Insert the filter code before the EXE definition
if 'exe = EXE(' in content:
    content = content.replace('exe = EXE(', filter_code + 'exe = EXE(')
    with open(spec_file, 'w') as f:
        f.write(content)
    print(f"✅ Filtered CUDA DLLs from {spec_file}")
