import pyopencl as cl
import os.path
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from skimage import color
from cython.parallel import prange
import time
import math

# A basic, parallelized Python implementation of 
# the Tilt-Shift effect we hope to achieve in OpenCL
    
# Adjusts the saturation of a pixel    
def saturation(p, value):
    red_v = p[0] * (1 - value) 
    blue_v = p[1] * (1 - value) 
    green_v = p[2] * (1 - value) 
    return [red_v, blue_v, green_v]
    
# Adjusts the contrast on a pixel    
def contrast(p, value):
    factor = (259 * (value + 255)) / float(255 * (259 - value))
    red = truncate(factor * (p[0] - 128) + 128)
    green = truncate(factor * (p[1] - 128) + 128)
    blue = truncate(factor * (p[2] - 128) + 128)
    return [red, green, blue]
    
# Ensures a pixel's value for a color is between 0 and 255
def truncate(value):
    if value < 0:
        value = 0
    elif value > 255:
        value = 255

    return value

# Rounds up the size to a be multiple of the group_size
def round_up(global_size, group_size):
    r = global_size % group_size
    if r == 0:
        return global_size
    return global_size + group_size - r

# Run a Python implementation of Tilt-Shift (grayscale)
if __name__ == '__main__':
    start_time = time.time()
    
    # List our platforms
    platforms = cl.get_platforms()
    print 'The platforms detected are:'
    print '---------------------------'
    for platform in platforms:
        print platform.name, platform.vendor, 'version:', platform.version
    
    # List devices in each platform
    for platform in platforms:
        print 'The devices detected on platform', platform.name, 'are:'
        print '---------------------------'
        for device in platform.get_devices():
            print device.name, '[Type:', cl.device_type.to_string(device.type), ']'
            print 'Maximum clock Frequency:', device.max_clock_frequency, 'MHz'
            print 'Maximum allocable memory size:', int(device.max_mem_alloc_size / 1e6), 'MB'
            print 'Maximum work group size', device.max_work_group_size
            print '---------------------------'

    # Create a context with all the devices
    devices = platforms[0].get_devices()
    context = cl.Context(devices[2:])
    print 'This context is associated with ', len(context.devices), 'devices'
    
    # Create a queue for transferring data and launching computations.
    # Turn on profiling to allow us to check event times.
    queue = cl.CommandQueue(context, context.devices[0],
                            properties=cl.command_queue_properties.PROFILING_ENABLE)
    print 'The queue is using the device:', queue.device.name

    curdir = os.path.dirname(os.path.realpath(__file__))
    program = cl.Program(context, open('TiltShiftColor.cl').read()).build(options=['-I', curdir])
    
    # Load the image
    input_image = mpimg.imread('../MITBoathouse.png',0)
    host_image_filtered = np.zeros_like(input_image)
    plt.imshow(input_image)    
    plt.show()
    
    gpu_image_a = cl.Buffer(context, cl.mem_flags.READ_WRITE, input_image.size * 4)
    gpu_image_b = cl.Buffer(context, cl.mem_flags.READ_WRITE, input_image.size * 4)
    
    local_size = (8, 8)  # This doesn't really affect speed for the Python implementation
    # We need to add [1:] because the first element in this list is the number of colors in RGB, namely 3
    global_size = tuple([round_up(g, l) for g, l in zip(input_image.shape[::-1][1:], local_size)])
    print global_size
    width = np.int32(input_image.shape[1])
    height = np.int32(input_image.shape[0])
    
    # Set up a (N+2 x N+2) local memory buffer.
    # +2 for 1-pixel halo on all sides, 4 bytes for float.
    local_memory = cl.LocalMemory(4 * (local_size[0] + 2) * (local_size[1] + 2))
    # Each work group will have its own private buffer.
    buf_width = np.int32(local_size[0] + 2)
    buf_height = np.int32(local_size[1] + 2)
    halo = np.int32(1)
    
    # Send image to the device, non-blocking
    cl.enqueue_copy(queue, gpu_image_a, input_image, is_blocking=False)
    
    ################################
    ### USER CHANGEABLE SETTINGS ###
    ################################
    # Number of Passes - 3 passes approximates Gaussian Blur
    num_passes = 3
    # Saturation - Between 0 and 1
    sat = np.float32(0.0)
    # Contrast - Between -255 and 255
    con = np.float32(0.0)
    # The y-index of the center of the in-focus region
    middle_in_focus = np.int32(600)
    # The number of pixels to either side of the middle_in_focus to keep in focus
    in_focus_radius = np.int32(50)

    print "Image Width %s" % width
    print "Image Height %s" % height
    
    # We will perform 3 passes of the bux blur 
    # effect to approximate Gaussian blurring
    for pass_num in range(num_passes):
        print "In iteration %s of %s" % (pass_num + 1, num_passes)
        # We need to loop over the workgroups here, 
        # because unlike OpenCL, they are not 
        # automatically set up by Python
        last_pass = np.bool_(False)
        if pass_num == num_passes - 1:
            print "---Last Pass---"
            last_pass = np.bool_(True)
            
        # Run tilt shift over the group and store the results in host_image_tilt_shifted
        # Loop over all groups and call tiltshift once per group    
        program.tiltshift(queue, global_size, local_size,
                          gpu_image_a, gpu_image_b, local_memory, 
                          width, height, 
                          buf_width, buf_height, halo,
                          sat, con, last_pass, 
                          middle_in_focus, in_focus_radius)

        # Now put the output of the last pass into the input of the next pass
        gpu_image_a, gpu_image_b = gpu_image_b, gpu_image_a
    
    cl.enqueue_copy(queue, host_image_filtered, gpu_image_a, is_blocking=True)
    
    end_time = time.time()
    print "Took %s seconds to run %s passes" % (end_time - start_time, num_passes)   
    
    # Display the new image
    plt.imshow(host_image_filtered)    
    plt.show()
    mpimg.imsave("MITBoathouseColorTS.png", host_image_filtered)